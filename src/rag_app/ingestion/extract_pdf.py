"""Stage 2 · Extract text from a text-based PDF with Poppler (D-028), page by page.

Poppler runs as a separate process with a fixed argument list and a timeout (no shell).
Scanned PDFs (no text layer), encrypted, and corrupt files are reported with specific codes.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from rag_app.core.errors import AppError, ErrorCode
from rag_app.ingestion.poppler import PopplerTools

_PAGES = re.compile(r"^Pages:\s+(\d+)", re.MULTILINE)
_ENCRYPTED = re.compile(r"^Encrypted:\s+yes", re.MULTILINE | re.IGNORECASE)


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603  (fixed argument list, no shell)
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(ErrorCode.EXTRACTION_TIMEOUT) from exc
    except OSError as exc:
        raise AppError(ErrorCode.POPPLER_MISSING, details={"error": str(exc)}) from exc


def extract_pdf_pages(path: Path, tools: PopplerTools, timeout: float = 60.0) -> list[str]:
    """Return the raw text of each page of ``path`` (pdftotext keeps reading order per page).

    Raises:
        AppError: ``PDF_ENCRYPTED``, ``PDF_CORRUPT``, ``PDF_NO_TEXT``, ``EXTRACTION_TIMEOUT``.
    """
    info = _run([str(tools.pdfinfo), str(path)], timeout)
    if _ENCRYPTED.search(info.stdout) or "Incorrect password" in info.stderr:
        raise AppError(ErrorCode.PDF_ENCRYPTED)
    match = _PAGES.search(info.stdout)
    if info.returncode != 0 or not match:
        raise AppError(ErrorCode.PDF_CORRUPT)
    page_count = int(match.group(1))

    result = _run([str(tools.pdftotext), "-enc", "UTF-8", str(path), "-"], timeout)
    if result.returncode != 0:
        raise AppError(ErrorCode.PDF_CORRUPT)
    pages = result.stdout.split("\f")[:page_count]
    if not any(page.strip() for page in pages):
        raise AppError(ErrorCode.PDF_NO_TEXT)
    return pages
