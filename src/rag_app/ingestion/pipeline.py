"""Ingestion pipeline, stages 2–4: file → blocks → chunks. No database, no network.

The caller (the ingestion worker) supplies the file and tools, records stage progress, runs
stage 5 (:mod:`rag_app.ingestion.embedding`), and stores the result in one transaction
(DESIGN-001 §7.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rag_app.config.settings import RagSettings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import ChunkDraft, DocumentFormat, ExtractedDocument, ProcessingStage
from rag_app.ingestion.chunking import chunk_blocks
from rag_app.ingestion.cleaning import clean_pdf_pages
from rag_app.ingestion.extract_markdown import extract_markdown
from rag_app.ingestion.extract_pdf import extract_pdf_pages
from rag_app.ingestion.normalization import normalize_arabic
from rag_app.ingestion.poppler import PopplerTools
from rag_app.ingestion.validation import decode_markdown


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Result of stages 2–4 for one document version."""

    chunks: tuple[ChunkDraft, ...]
    page_count: int | None


def extract(
    path: Path, fmt: DocumentFormat, poppler: Callable[[], PopplerTools], timeout: float
) -> ExtractedDocument:
    """Stage 2–3: extract and clean the file into structured blocks."""
    if fmt is DocumentFormat.PDF:
        return clean_pdf_pages(extract_pdf_pages(path, poppler(), timeout))
    return extract_markdown(decode_markdown(path.read_bytes()))


def process_file(
    path: Path,
    fmt: DocumentFormat,
    rag: RagSettings,
    *,
    poppler: Callable[[], PopplerTools],
    timeout: float = 60.0,
    on_stage: Callable[[ProcessingStage], None] = lambda _stage: None,
) -> ProcessedDocument:
    """Run stages 2–4 on ``path`` and return the chunks.

    ``on_stage`` is called before each stage so progress can be shown (FR-ING-02) and so the
    caller can stop a cancelled job between stages (DD-02) by raising from the callback.

    Raises:
        AppError: extraction errors, or ``PDF_NO_TEXT`` when no chunk could be produced.
    """
    on_stage(ProcessingStage.EXTRACTING)
    document = extract(path, fmt, poppler, timeout)
    on_stage(ProcessingStage.CHUNKING)
    chunks = chunk_blocks(
        document.blocks, size=rag.chunk_chars, overlap=rag.chunk_overlap, normalize=normalize_arabic
    )
    if not chunks:
        raise AppError(ErrorCode.PDF_NO_TEXT if fmt is DocumentFormat.PDF else ErrorCode.EMPTY_FILE)
    return ProcessedDocument(chunks=tuple(chunks), page_count=document.page_count)
