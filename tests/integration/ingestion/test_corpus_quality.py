"""NFR-LNG-02 (SRS v1.1) acceptance on the real sample corpus, run in CI on Linux and Windows.

(a) letter error ≤ 1% between each PDF's extracted text and its reference text;
(b) 100% of golden-set evidence passages remain intact in the produced chunks.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path

import pytest
import yaml

from rag_app.config.settings import RagSettings
from rag_app.domain.models import Block, DocumentFormat
from rag_app.ingestion.pipeline import extract, process_file
from rag_app.ingestion.poppler import locate_poppler
from support.embeddings import FakeEmbedder

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="Poppler not installed"),
]

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "sample_corpus"
MANIFEST = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
GOLDEN = yaml.safe_load((ROOT / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))
_UNIFY = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_FOOTER = re.compile(r"منصة\s*ضفيرة\s*[—–-]?\s*صفحة\s*\d+\s*من\s*\d+")


def skeleton(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.replace("**", ""))
    text = text.translate(_DIGITS).translate(_UNIFY)
    text = re.sub("[\u064b-\u065f\u0670\u0640]", "", text)
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LN")


# Known limitation accepted by the owner (D-037): in D02 v1 the cell "حتى 3 مستخدمين"
# wraps onto two lines and pdftotext emits the second line after the table. Only table-aware
# extraction can restore it. strict=True makes the test fail loudly once the gap is fixed.
_KNOWN_GAPS = {("D02", "v1"): "wrapped table cell is split by pdftotext reading order"}

VERSIONS = [
    pytest.param(
        doc["id"],
        v["version"],
        CORPUS / v["upload_file"],
        DocumentFormat(v["format"]),
        id=f"{doc['id']}-{v['version']}",
        marks=[pytest.mark.xfail(strict=True, reason=_KNOWN_GAPS[doc["id"], v["version"]])]
        if (doc["id"], v["version"]) in _KNOWN_GAPS
        else [],
    )
    for doc in MANIFEST["documents"]
    for v in doc["versions"]
]


def _evidence_for(doc_id: str, version: str) -> list[dict]:
    active_states = [s for s, m in MANIFEST["states"].items() if m[doc_id] == version]
    found = []
    for q in GOLDEN["questions"]:
        variants = q.get("by_state") or {MANIFEST["default_state"]: q}
        for state, v in variants.items():
            if state in active_states:
                found += [
                    e
                    for e in v.get("evidence") or []
                    if e["doc"] == doc_id and e.get("version", version) == version
                ]
    return found


@pytest.mark.parametrize(("doc_id", "version", "path", "fmt"), VERSIONS)
def test_all_golden_evidence_is_intact_in_chunks(
    doc_id: str, version: str, path: Path, fmt: DocumentFormat
) -> None:
    chunks = process_file(
        path, fmt, RagSettings(), poppler=locate_poppler, embedder=FakeEmbedder
    ).chunks
    skeletons = [skeleton(c.text_original) for c in chunks]

    evidence = _evidence_for(doc_id, version)
    missing = [
        e["snippets"]
        for e in evidence
        if not any(all(skeleton(s) in sk for s in e["snippets"]) for sk in skeletons)
    ]

    assert evidence, "every corpus version is cited by the golden set"
    assert missing == []


def _as_text(blocks: tuple[Block, ...]) -> str:
    """Rebuild the document text: headings live in heading paths, not in blocks."""
    lines: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        lines += [h for h in block.heading_path if h not in seen]
        seen.update(block.heading_path)
        lines.append(block.text)
    return "\n".join(lines)


@pytest.mark.parametrize("pdf", sorted((CORPUS / "pdf").glob("*.pdf")), ids=lambda p: p.stem)
def test_pdf_letter_error_is_at_most_one_percent(pdf: Path) -> None:
    reference = (CORPUS / "reference_text" / f"{pdf.stem}.txt").read_text(encoding="utf-8")
    document = extract(pdf, DocumentFormat.PDF, locate_poppler, timeout=60)
    extracted = _as_text(document.blocks)
    ref = Counter(skeleton(_FOOTER.sub(" ", reference)))
    got = Counter(skeleton(extracted))
    total = sum(ref.values())
    error = sum(abs(ref[c] - got[c]) for c in set(ref) | set(got)) / total

    assert error <= 0.01, f"letter error {error:.2%}"
