"""Phase 3 PoC: compare PDF text extractors on the Arabic sample corpus.

Measures, per extractor and PDF, against the reference text rendered when the
PDF was built (data/sample_corpus/reference_text/):
  - letter error   : order-insensitive character error (is the text correct?)
  - letter CER     : Levenshtein on letters/digits only (correct and in order?)
  - punct CER      : as above, punctuation kept
  - word recall    : reference words found intact (spacing problems)
  - pres. forms    : Arabic presentation-form code points emitted (before NFKC)
  - time           : wall-clock extraction time

The metric definitions are shared with tools/corpus/verify_corpus.py, so the
numbers are comparable with docs/02_SAMPLE_CORPUS.md.

Usage (from poc/extraction):  .venv/bin/python bench_pdf_extractors.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "corpus"))
import verify_corpus as m  # noqa: E402  (shared metric definitions)

from rapidfuzz.distance import Levenshtein  # noqa: E402

PDF_DIR = ROOT / "data" / "sample_corpus" / "pdf"
REF_DIR = ROOT / "data" / "sample_corpus" / "reference_text"


# --------------------------------------------------------------------------- #
# Extractors (each returns the full text of the PDF)
# --------------------------------------------------------------------------- #
def ex_pdftotext(path: Path) -> str:
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"],
                          check=True, capture_output=True, text=True).stdout


def ex_pypdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)


def ex_pypdf_layout(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in PdfReader(path).pages)


def ex_pdfminer(path: Path) -> str:
    from pdfminer.high_level import extract_text
    return extract_text(str(path))


def ex_pdfplumber(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def ex_pypdfium2(path: Path) -> str:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        out = []
        for page in doc:
            tp = page.get_textpage()
            out.append(tp.get_text_bounded())
            tp.close()
            page.close()
        return "\n".join(out)
    finally:
        doc.close()


def ex_pymupdf(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(p.get_text("text") for p in doc)


def ex_pymupdf_sorted(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(p.get_text("text", sort=True) for p in doc)


EXTRACTORS = {
    "pdftotext (poppler)": ex_pdftotext,
    "pypdf": ex_pypdf,
    "pypdf (layout mode)": ex_pypdf_layout,
    "pdfminer.six": ex_pdfminer,
    "pdfplumber": ex_pdfplumber,
    "pypdfium2": ex_pypdfium2,
    "PyMuPDF": ex_pymupdf,
    "PyMuPDF (sort=True)": ex_pymupdf_sorted,
}


def measure(reference: str, extracted: str) -> dict:
    ref_l, ref_p = m.letters_only(reference), m.normalize_for_comparison(reference)
    return {
        "letter_error": m.letter_multiset_error(reference, extracted),
        "letter_cer": Levenshtein.distance(ref_l, m.letters_only(extracted)) / max(len(ref_l), 1),
        "punct_cer": Levenshtein.distance(ref_p, m.normalize_for_comparison(extracted)) / max(len(ref_p), 1),
        "word_recall": m.word_recall(reference, extracted),
        "presentation_forms": m.presentation_form_count(extracted),
    }


def main() -> None:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    results: dict[str, dict] = {}
    for name, fn in EXTRACTORS.items():
        per_pdf = {}
        for pdf in pdfs:
            reference = (REF_DIR / f"{pdf.stem}.txt").read_text(encoding="utf-8")
            fn(pdf)  # warm-up (imports, caches) so timing reflects extraction only
            t0 = time.perf_counter()
            text = fn(pdf)
            elapsed = (time.perf_counter() - t0) * 1000
            per_pdf[pdf.stem] = {**measure(reference, text), "ms": elapsed}
        results[name] = per_pdf

    keys = ["letter_error", "letter_cer", "punct_cer", "word_recall"]
    print("| Extractor | Letter error | Letter CER | Punct. CER | Word recall | Pres. forms (total) | ms / PDF |")
    print("|---|---|---|---|---|---|---|")
    for name, per_pdf in results.items():
        vals = list(per_pdf.values())
        cells = [f"{100 * mean(v[k] for v in vals):.1f}%" for k in keys]
        pf = sum(v["presentation_forms"] for v in vals)
        ms = mean(v["ms"] for v in vals)
        print(f"| {name} | " + " | ".join(cells) + f" | {pf} | {ms:.0f} |")

    out = Path(__file__).with_name("results_pdf_extractors.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetailed results: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
