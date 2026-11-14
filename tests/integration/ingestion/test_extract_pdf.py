"""PDF extraction failure paths (FR-DOC-03, DESIGN-001 §7.2) against the real Poppler tools."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from rag_app.core.errors import AppError, ErrorCode
from rag_app.ingestion.extract_pdf import extract_pdf_pages
from rag_app.ingestion.poppler import PopplerTools, locate_poppler
from support import pdfs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pdftotext") is None, reason="Poppler not installed"),
]

CORPUS_PDF = Path(__file__).resolve().parents[3] / "data/sample_corpus/pdf/05_privacy_security.pdf"


def test_text_pdf_gives_one_text_per_page() -> None:
    pages = extract_pdf_pages(CORPUS_PDF, locate_poppler())

    assert len(pages) >= 2
    assert "سياسة الخصوصية" in pages[0]


@pytest.mark.parametrize(
    ("factory", "code"),
    [
        (pdfs.blank_pdf, ErrorCode.PDF_NO_TEXT),  # what a scanned PDF looks like
        (pdfs.encrypted_pdf, ErrorCode.PDF_ENCRYPTED),
        (pdfs.corrupt_pdf, ErrorCode.PDF_CORRUPT),
    ],
    ids=["no-text", "encrypted", "corrupt"],
)
def test_unusable_pdfs_are_rejected_with_specific_codes(
    tmp_path: Path, factory: object, code: ErrorCode
) -> None:
    path = pdfs.write(tmp_path / "bad.pdf", factory())  # type: ignore[operator]

    with pytest.raises(AppError) as info:
        extract_pdf_pages(path, locate_poppler())

    assert info.value.code is code


def test_missing_executable_is_reported(tmp_path: Path) -> None:
    ghost = PopplerTools(tmp_path / "nope", tmp_path / "nope", "0")

    with pytest.raises(AppError) as info:
        extract_pdf_pages(CORPUS_PDF, ghost)

    assert info.value.code is ErrorCode.POPPLER_MISSING


def test_timeout_is_reported(tmp_path: Path) -> None:
    # A stand-in "pdfinfo" that sleeps longer than the timeout.
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    slow = PopplerTools(Path(sys.executable), Path(sys.executable), "0")

    with pytest.raises(AppError) as info:
        extract_pdf_pages(script, slow, timeout=0.2)

    assert info.value.code is ErrorCode.EXTRACTION_TIMEOUT
