"""Stage 1 · Validate an uploaded file by its content, not only its name.

Requirements: FR-DOC-02/03, NFR-SEC-02.
"""

from __future__ import annotations

from pathlib import PurePath

from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import DocumentFormat

PDF_MAGIC = b"%PDF-"
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})


def detect_format(filename: str, head: bytes) -> DocumentFormat:
    """Return the format of an upload from its extension **and** first bytes.

    A ``.pdf`` must start with the PDF signature; a Markdown file must not look like a PDF.
    Any mismatch or other extension is rejected, so a renamed file cannot slip through.

    Raises:
        AppError: ``EMPTY_FILE`` or ``UNSUPPORTED_TYPE``.
    """
    if not head:
        raise AppError(ErrorCode.EMPTY_FILE)
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf" and head.startswith(PDF_MAGIC):
        return DocumentFormat.PDF
    if suffix in MARKDOWN_SUFFIXES and not head.startswith(PDF_MAGIC):
        return DocumentFormat.MARKDOWN
    raise AppError(ErrorCode.UNSUPPORTED_TYPE, details={"filename": PurePath(filename).name})


def decode_markdown(data: bytes) -> str:
    """Decode a Markdown upload as strict UTF-8 (a leading BOM is allowed and removed).

    Raises:
        AppError: ``INVALID_UTF8`` for undecodable bytes or NUL characters (binary content).
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(ErrorCode.INVALID_UTF8) from exc
    if "\x00" in text:
        raise AppError(ErrorCode.INVALID_UTF8)
    if not text.strip():
        raise AppError(ErrorCode.EMPTY_FILE)
    return text


def safe_display_name(filename: str) -> str:
    """Human-readable document name from an upload name: no folders, no extension, trimmed."""
    stem = PurePath(filename.replace("\\", "/")).stem.strip()
    return stem[:200] or "مستند"
