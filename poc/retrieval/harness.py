"""Phase 3 PoC: retrieval evaluation harness for the Dafira golden set.

Throwaway measurement code (not the application). It answers, with numbers:
  - how much the PDF extractor choice affects retrieval (pdftotext vs pypdfium2);
  - how much Arabic normalization affects retrieval;
  - how a lexical baseline (BM25) compares with embedding providers.

Pipeline per configuration:
  load active document versions (manifest default state)
  -> extract text (Markdown as-is; PDF via the selected extractor)
  -> chunk (heading-aware, size-bounded, with overlap)
  -> index (BM25 or embeddings)
  -> run every answerable golden-set question
  -> metrics: Hit@k, Recall@k (evidence entries covered), MRR

Relevance: a chunk is relevant to an evidence entry when it comes from the cited
document and contains every evidence snippet. Matching uses a "skeleton"
(normalized letters and digits only, no spaces or punctuation), so it is
robust to spacing and punctuation artifacts of PDF extraction.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "sample_corpus"
GOLDEN = ROOT / "eval" / "golden_set.yaml"

# --------------------------------------------------------------------------- #
# Arabic normalization
# --------------------------------------------------------------------------- #
TASHKEEL = re.compile("[ً-ٰٟ]")
TATWEEL = "ـ"
BIDI = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩"), None)
ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})
YAA_TAA = str.maketrans({"ى": "ي", "ة": "ه"})


@dataclass(frozen=True)
class Normalization:
    """Which normalization steps to apply (each one is measured separately)."""
    nfkc: bool = True            # fold presentation forms / compatibility chars
    tashkeel: bool = True        # remove diacritics and tatweel
    digits: bool = True          # Arabic-Indic -> Western digits
    alef: bool = False           # unify alef variants
    yaa_taa: bool = False        # ى -> ي, ة -> ه

    def apply(self, text: str) -> str:
        if self.nfkc:
            text = unicodedata.normalize("NFKC", text)
        text = text.translate(BIDI)
        if self.tashkeel:
            text = TASHKEEL.sub("", text).replace(TATWEEL, "")
        if self.digits:
            text = text.translate(ARABIC_INDIC)
        if self.alef:
            text = text.translate(ALEF)
        if self.yaa_taa:
            text = text.translate(YAA_TAA)
        return text


MATCH_NORM = Normalization(alef=True, yaa_taa=True)


def skeleton(text: str) -> str:
    """Letters and digits only, fully normalized; used for relevance matching."""
    text = MATCH_NORM.apply(text.replace("**", ""))
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LN")


# --------------------------------------------------------------------------- #
# Corpus loading and extraction
# --------------------------------------------------------------------------- #
def extract_pdftotext(path: Path) -> str:
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"],
                          check=True, capture_output=True, text=True).stdout


def extract_pypdfium2(path: Path) -> str:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        pages = []
        for page in doc:
            tp = page.get_textpage()
            pages.append(tp.get_text_bounded())
            tp.close()
            page.close()
        return "\n".join(pages)
    finally:
        doc.close()


PDF_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    "pdftotext": extract_pdftotext,
    "pypdfium2": extract_pypdfium2,
}

FOOTER = re.compile(r"منصة\s*ضفيرة\s*[—–-]?\s*صفحة\s*\d+\s*من\s*\d+")


@dataclass
class Document:
    doc_id: str
    version: str
    fmt: str
    text: str


def load_documents(state: str | None, pdf_extractor: str) -> list[Document]:
    manifest = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
    active = manifest["states"][state or manifest["default_state"]]
    docs = []
    for doc in manifest["documents"]:
        ver = next(v for v in doc["versions"] if v["version"] == active[doc["id"]])
        path = CORPUS / ver["upload_file"]
        if ver["format"] == "pdf":
            text = PDF_EXTRACTORS[pdf_extractor](path).translate(BIDI)
            text = FOOTER.sub(" ", text)  # minimal cleaning: repeated page footer
        else:
            text = path.read_text(encoding="utf-8")
        docs.append(Document(doc["id"], ver["version"], ver["format"], text))
    return docs


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    version: str
    heading: str
    text: str
    skel: str = field(default="", repr=False)


HEADING_MD = re.compile(r"^(#{1,6})\s+(.*)$")
NUMBERED_HEADING = re.compile(r"^\s*(?:[0-9٠-٩]+\s*\.|\.\s*[0-9٠-٩]+)\s*\S")


def split_sections(doc: Document) -> list[tuple[str, str]]:
    """Split a document into (heading, body) sections.

    Markdown: by '#' headings. PDF text: by lines that look like numbered
    section headings (e.g. '2. مقارنة الخطط', or '.٢ ...' as pdftotext emits).
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in doc.text.splitlines():
        is_heading = False
        title = ""
        if doc.fmt == "markdown":
            m = HEADING_MD.match(line)
            if m:
                is_heading, title = True, m.group(2).strip()
        elif NUMBERED_HEADING.match(line) and len(line) < 80:
            is_heading, title = True, line.strip()
        if is_heading:
            sections.append((title, [line]))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(lines).strip()) for h, lines in sections if "\n".join(lines).strip()]


def window(text: str, size: int, overlap: int) -> Iterable[str]:
    """Split text into windows of ~size characters on whitespace, with overlap."""
    if len(text) <= size:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + size // 2, end)
            end = cut if cut != -1 else end
        yield text[start:end].strip()
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def chunk_documents(docs: list[Document], size: int = 800, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        n = 0
        for heading, body in split_sections(doc):
            for piece in window(body, size, overlap):
                if not piece:
                    continue
                # Prefix the section heading so each chunk carries its context.
                text = piece if piece.startswith(heading) else f"{heading}\n{piece}" if heading else piece
                chunks.append(Chunk(f"{doc.doc_id}-{doc.version}-{n:03d}", doc.doc_id, doc.version, heading, text))
                n += 1
    for c in chunks:
        c.skel = skeleton(c.text)
    return chunks


# --------------------------------------------------------------------------- #
# Golden set and relevance
# --------------------------------------------------------------------------- #
@dataclass
class Question:
    qid: str
    category: str
    text: str
    answerable: bool
    evidence: list[dict]


def load_questions(state: str | None) -> list[Question]:
    manifest = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
    state = state or manifest["default_state"]
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    out = []
    for q in data["questions"]:
        v = q.get("by_state", {}).get(state, q)
        out.append(Question(q["id"], q["category"], q["question"],
                            v["expected_outcome"] == "answered", v.get("evidence") or []))
    return out


def relevant(chunk: Chunk, ev: dict) -> bool:
    return chunk.doc_id == ev["doc"] and all(skeleton(s) in chunk.skel for s in ev["snippets"])


def coverage_report(chunks: list[Chunk], questions: list[Question]) -> list[str]:
    """Evidence entries that no chunk satisfies (chunking or extraction broke them)."""
    missing = []
    for q in questions:
        for ev in q.evidence:
            if not any(relevant(c, ev) for c in chunks):
                missing.append(f"{q.qid}:{ev['doc']}:{ev['section']}")
    return missing


# --------------------------------------------------------------------------- #
# Retrievers
# --------------------------------------------------------------------------- #
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")


def tokenize(text: str, norm: Normalization, light_stem: bool) -> list[str]:
    toks = TOKEN.findall(norm.apply(text).lower())
    if light_stem:
        out = []
        for t in toks:
            for p in PREFIXES:
                if t.startswith(p) and len(t) - len(p) >= 2:
                    t = t[len(p):]
                    break
            out.append(t)
        toks = out
    return toks


class BM25:
    """Okapi BM25, implemented directly for transparency (k1=1.5, b=0.75)."""

    def __init__(self, chunks: list[Chunk], norm: Normalization, light_stem: bool = False,
                 k1: float = 1.5, b: float = 0.75):
        self.chunks, self.norm, self.stem, self.k1, self.b = chunks, norm, light_stem, k1, b
        self.docs = [Counter(tokenize(c.text, norm, light_stem)) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / len(self.lens)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        q = tokenize(query, self.norm, self.stem)
        scores = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in q:
                tf = d.get(t)
                if tf:
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            scores.append((self.chunks[i], s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(search: Callable[[str, int], list[tuple[Chunk, float]]],
             questions: list[Question], ks=(1, 3, 5, 10)) -> dict:
    answerable = [q for q in questions if q.answerable]
    kmax = max(ks)
    hits = {k: 0 for k in ks}
    recall = {k: 0.0 for k in ks}
    rr = 0.0
    per_question = {}
    unanswerable_top = []
    for q in questions:
        results = search(q.text, kmax)
        if not q.answerable:
            unanswerable_top.append(results[0][1] if results else 0.0)
            continue
        first = None
        for rank, (c, _) in enumerate(results, 1):
            if any(relevant(c, ev) for ev in q.evidence):
                first = rank
                break
        rr += 1 / first if first else 0
        for k in ks:
            top = [c for c, _ in results[:k]]
            covered = sum(1 for ev in q.evidence if any(relevant(c, ev) for c in top))
            recall[k] += covered / len(q.evidence)
            hits[k] += 1 if first and first <= k else 0
        per_question[q.qid] = {"first_relevant_rank": first,
                               "top_score": results[0][1] if results else 0.0}
    n = len(answerable)
    return {
        "answerable_questions": n,
        **{f"hit@{k}": hits[k] / n for k in ks},
        **{f"recall@{k}": recall[k] / n for k in ks},
        "mrr": rr / n,
        "per_question": per_question,
        "unanswerable_top_scores": unanswerable_top,
    }
