"""Acceptance checks for the Dafira sample corpus and golden set (Phase 2).

Development-only tool. It checks:

1. Fact registry (data/sample_corpus/facts.yaml): every registered fact appears
   verbatim in every document that is expected to state it.
2. Golden set (eval/golden_set.yaml): schema, unique ids, category coverage,
   share of unanswerable questions, and that every evidence snippet occurs
   verbatim inside the named section of the named document version.
3. PDFs (data/sample_corpus/pdf/): each has a text layer, and text extracted
   from it matches the reference text rendered by build_pdfs.mjs. Two
   independent extractors are measured (poppler's pdftotext and pypdf).

Usage (from tools/corpus):
    .venv/bin/python verify_corpus.py            # all checks
    .venv/bin/python verify_corpus.py --json out.json

Exit code is non-zero if any acceptance check fails.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pypdf import PdfReader
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "sample_corpus"
GOLDEN = ROOT / "eval" / "golden_set.yaml"

CATEGORIES = {
    "single_doc", "numeric_table", "paraphrased", "multi_doc",
    "version_sensitive", "unanswerable", "out_of_scope",
}
OUTCOMES = {"answered", "insufficient_information"}
MIN_QUESTIONS, MAX_QUESTIONS = 40, 60
UNANSWERABLE_SHARE = (0.15, 0.25)  # unanswerable + out_of_scope, default state
# Acceptance for the corpus PDFs (reference extractor: pdftotext):
# the text layer must map glyphs to the right characters. This is measured as
# the letter-multiset error (order-insensitive). Order and spacing artifacts
# (table cells reflowed across lines, bidi placement of digits and Latin runs,
# spurious spaces inside words) are reported as information for Phase 3,
# because they depend on the extractor and are handled by cleaning/chunking.
PDF_MAX_LETTER_MULTISET_ERROR = 0.01

# Footer added by build_pdfs.mjs on every page; excluded before comparison.
FOOTER_RE = re.compile(r"منصة\s*ضفيرة\s*[—–-]?\s*صفحة\s*\d+\s*من\s*\d+")
BIDI_CONTROLS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩"), None)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


# --------------------------------------------------------------------------- #
# Markdown helpers
# --------------------------------------------------------------------------- #
def strip_emphasis(text: str) -> str:
    return text.replace("**", "")


def sections(markdown: str) -> dict[str, str]:
    """Map each '## ' heading text to the text up to the next '## ' heading."""
    result: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None:
                result[current] = "\n".join(buf)
            current, buf = line[3:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf)
    return result


def load_manifest() -> dict:
    return yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))


def version_sources(manifest: dict) -> dict[tuple[str, str], Path]:
    out = {}
    for doc in manifest["documents"]:
        for ver in doc["versions"]:
            out[(doc["id"], ver["version"])] = CORPUS / ver["source"]
    return out


# --------------------------------------------------------------------------- #
# 1. Facts
# --------------------------------------------------------------------------- #
def check_facts(report: Report) -> None:
    facts = yaml.safe_load((CORPUS / "facts.yaml").read_text(encoding="utf-8"))["facts"]
    sources = {p.stem: p.read_text(encoding="utf-8") for p in (CORPUS / "source").glob("*.md")}
    checked = 0
    for fact in facts:
        for stem, expected in fact["occurrences"].items():
            if stem not in sources:
                report.error(f"facts {fact['id']}: unknown document '{stem}'")
                continue
            for text in expected:
                checked += 1
                if text not in sources[stem]:
                    report.error(f"facts {fact['id']}: '{text}' not found in {stem}")
    report.info["facts"] = {"facts": len(facts), "occurrences_checked": checked}


# --------------------------------------------------------------------------- #
# 2. Golden set
# --------------------------------------------------------------------------- #
def check_evidence(report: Report, qid: str, evidence: list, state: dict, sources: dict) -> None:
    for ev in evidence:
        doc = ev.get("doc")
        version = ev.get("version") or state.get(doc)
        if (doc, version) not in sources:
            report.error(f"{qid}: unknown document/version {doc}/{version}")
            continue
        if ev.get("version") and state.get(doc) != ev["version"]:
            report.error(f"{qid}: evidence cites {doc}/{ev['version']} which is not active in this state")
        secs = sections(sources[(doc, version)].read_text(encoding="utf-8"))
        section = ev.get("section")
        if section not in secs:
            report.error(f"{qid}: section '{section}' not found in {doc}/{version}")
            continue
        body = strip_emphasis(secs[section])
        snippets = ev.get("snippets") or []
        if not snippets:
            report.error(f"{qid}: evidence without snippets")
        for snip in snippets:
            if snip not in body:
                report.error(f"{qid}: snippet '{snip}' not in {doc}/{version} § '{section}'")


def check_golden(report: Report) -> None:
    manifest = load_manifest()
    sources = version_sources(manifest)
    states = manifest["states"]
    default_state = manifest["default_state"]
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    questions = data["questions"]

    ids = [q["id"] for q in questions]
    for dup, n in Counter(ids).items():
        if n > 1:
            report.error(f"golden: duplicate id {dup}")

    categories = Counter()
    insufficient_default = 0
    for q in questions:
        qid = q["id"]
        cat = q.get("category")
        if cat not in CATEGORIES:
            report.error(f"{qid}: invalid category {cat}")
        categories[cat] += 1
        if not q.get("question"):
            report.error(f"{qid}: empty question")

        variants = q.get("by_state") or {default_state: q}
        if cat == "version_sensitive" and "by_state" not in q:
            report.error(f"{qid}: version_sensitive question needs by_state")
        for state_name, v in variants.items():
            if state_name not in states:
                report.error(f"{qid}: unknown state {state_name}")
                continue
            outcome = v.get("expected_outcome")
            if outcome not in OUTCOMES:
                report.error(f"{qid}/{state_name}: invalid expected_outcome {outcome}")
            if not v.get("reference_answer"):
                report.error(f"{qid}/{state_name}: missing reference_answer")
            evidence = v.get("evidence") or []
            if outcome == "answered" and not evidence:
                report.error(f"{qid}/{state_name}: answered question without evidence")
            if outcome == "insufficient_information" and evidence:
                report.error(f"{qid}/{state_name}: insufficient_information question with evidence")
            check_evidence(report, qid, evidence, states[state_name], sources)
            if state_name == default_state and outcome == "insufficient_information":
                insufficient_default += 1

    total = len(questions)
    if not MIN_QUESTIONS <= total <= MAX_QUESTIONS:
        report.error(f"golden: {total} questions, expected {MIN_QUESTIONS}-{MAX_QUESTIONS}")
    missing = CATEGORIES - set(categories)
    if missing:
        report.error(f"golden: categories without questions: {sorted(missing)}")
    share = insufficient_default / total if total else 0
    lo, hi = UNANSWERABLE_SHARE
    if not lo <= share <= hi:
        report.error(f"golden: insufficient-information share {share:.0%} outside {lo:.0%}-{hi:.0%}")
    multi_doc_ok = sum(
        1 for q in questions
        if len({e["doc"] for e in (q.get("evidence") or [])}) > 1
    )
    report.info["golden"] = {
        "questions": total,
        "categories": dict(sorted(categories.items())),
        "insufficient_information_share_default_state": round(share, 3),
        "questions_with_evidence_from_2plus_documents": multi_doc_ok,
    }


# --------------------------------------------------------------------------- #
# 3. PDFs
# --------------------------------------------------------------------------- #
TASHKEEL_RE = re.compile("[\u064B-\u065F\u0670\u0640]")  # harakat, superscript alef, tatweel


def _base(text: str) -> str:
    """NFKC (folds presentation forms), drop bidi controls, page footer, tashkeel and tatweel."""
    text = FOOTER_RE.sub(" ", unicodedata.normalize("NFKC", text).translate(BIDI_CONTROLS))
    return TASHKEEL_RE.sub("", text)


def letters_only(text: str) -> str:
    """Level 1 comparison: letters, digits and symbols in order. Whitespace and
    punctuation are removed because their placement in right-to-left text is a
    known extractor-side bidi problem, measured separately (level 2)."""
    return "".join(ch for ch in _base(text) if unicodedata.category(ch)[0] not in "PZC")


def normalize_for_comparison(text: str) -> str:
    """Level 2 comparison: as level 1, but punctuation is kept."""
    return "".join(ch for ch in _base(text) if unicodedata.category(ch)[0] not in "ZC")


def _words(text: str) -> Counter:
    return Counter(w for w in (letters_only(t) for t in _base(text).split()) if w)


def word_recall(reference: str, extracted: str) -> float:
    """Share of reference words (multiset, punctuation and tashkeel removed)
    found intact in the extracted text; insensitive to word order. Detects
    words split by spurious spaces or broken letters."""
    ref, ext = _words(reference), _words(extracted)
    total = sum(ref.values())
    return sum(min(n, ext[w]) for w, n in ref.items()) / total if total else 0.0


def letter_multiset_error(reference: str, extracted: str) -> float:
    """Order-insensitive share of letters/digits that differ: sum of absolute
    count differences per character, divided by the reference length."""
    ref, ext = Counter(letters_only(reference)), Counter(letters_only(extracted))
    total = sum(ref.values())
    diff = sum(abs(ref[c] - ext[c]) for c in set(ref) | set(ext))
    return diff / total if total else 0.0


def presentation_form_count(text: str) -> int:
    return sum(1 for ch in text if 0xFB50 <= ord(ch) <= 0xFDFF or 0xFE70 <= ord(ch) <= 0xFEFF)


def extract_pdftotext(path: Path) -> str:
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"],
                          check=True, capture_output=True, text=True).stdout


def extract_pypdf(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def check_pdfs(report: Report) -> None:
    if shutil.which("pdftotext") is None:
        report.error("pdf: pdftotext (poppler) is not installed")
        return
    results = {}
    for pdf in sorted((CORPUS / "pdf").glob("*.pdf")):
        ref_path = CORPUS / "reference_text" / (pdf.stem + ".txt")
        if not ref_path.exists():
            report.error(f"pdf {pdf.name}: missing reference text")
            continue
        reference = ref_path.read_text(encoding="utf-8")
        ref_letters, ref_punct = letters_only(reference), normalize_for_comparison(reference)
        pages = PdfReader(pdf).pages
        entry = {"pages": len(pages)}
        if any(not (p.extract_text() or "").strip() for p in pages):
            report.error(f"pdf {pdf.name}: a page has no extractable text layer")
        for name, extractor in (("pdftotext", extract_pdftotext), ("pypdf", extract_pypdf)):
            raw = extractor(pdf)
            cer = Levenshtein.distance(ref_letters, letters_only(raw)) / max(len(ref_letters), 1)
            cer_p = Levenshtein.distance(ref_punct, normalize_for_comparison(raw)) / max(len(ref_punct), 1)
            entry[name] = {
                "letter_multiset_error": round(letter_multiset_error(reference, raw), 4),
                "cer_letters": round(cer, 4),
                "cer_with_punctuation": round(cer_p, 4),
                "word_recall": round(word_recall(reference, raw), 4),
                "presentation_form_chars_before_nfkc": presentation_form_count(raw),
            }
        lme = entry["pdftotext"]["letter_multiset_error"]
        if lme > PDF_MAX_LETTER_MULTISET_ERROR:
            report.error(
                f"pdf {pdf.name}: pdftotext letter-multiset error {lme:.2%} "
                f"exceeds {PDF_MAX_LETTER_MULTISET_ERROR:.0%}"
            )
        results[pdf.name] = entry
    report.info["pdfs"] = results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="write the report as JSON to this path")
    args = parser.parse_args()

    report = Report()
    check_facts(report)
    check_golden(report)
    check_pdfs(report)

    print(json.dumps(report.info, ensure_ascii=False, indent=2))
    if args.json:
        args.json.write_text(json.dumps({"info": report.info, "errors": report.errors},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
    if report.errors:
        print(f"\nFAILED: {len(report.errors)} problem(s)", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\nOK: all corpus acceptance checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
