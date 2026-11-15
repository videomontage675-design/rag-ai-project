"""Ingestion pipeline, stages 2–5: file → blocks → chunks → vectors. No database access.

The caller (the ingestion worker) supplies the file, Poppler, and the embedding provider,
records stage progress, and stores the result in one transaction (DESIGN-001 §7.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rag_app.config.settings import RagSettings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import (
    ChunkDraft,
    DocumentFormat,
    EmbeddingIdentity,
    ExtractedDocument,
    ProcessingStage,
)
from rag_app.ingestion.chunking import chunk_blocks
from rag_app.ingestion.cleaning import clean_pdf_pages
from rag_app.ingestion.embedding import embed_chunks
from rag_app.ingestion.extract_markdown import extract_markdown
from rag_app.ingestion.extract_pdf import extract_pdf_pages
from rag_app.ingestion.normalization import normalize_arabic
from rag_app.ingestion.poppler import PopplerTools
from rag_app.ingestion.validation import decode_markdown
from rag_app.providers.ports import EmbeddingProvider, Vectors


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Result of stages 2–5 for one document version; ``vectors[i]`` embeds ``chunks[i]``."""

    chunks: tuple[ChunkDraft, ...]
    page_count: int | None
    vectors: Vectors
    embedding: EmbeddingIdentity


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
    embedder: Callable[[], EmbeddingProvider],
    timeout: float = 60.0,
    on_stage: Callable[[ProcessingStage], None] = lambda _stage: None,
) -> ProcessedDocument:
    """Run stages 2–5 on ``path`` and return the chunks with their vectors.

    ``on_stage`` is called before each stage so progress can be shown (FR-ING-02) and so the
    caller can stop a cancelled job between stages (DD-02) by raising from the callback.

    Raises:
        AppError: extraction errors, ``PDF_NO_TEXT``/``EMPTY_FILE`` when no chunk could be
            produced, or ``PROVIDER_*`` when embedding fails after retries (FR-ING-11).
    """
    on_stage(ProcessingStage.EXTRACTING)
    document = extract(path, fmt, poppler, timeout)
    on_stage(ProcessingStage.CHUNKING)
    chunks = chunk_blocks(
        document.blocks, size=rag.chunk_chars, overlap=rag.chunk_overlap, normalize=normalize_arabic
    )
    if not chunks:
        raise AppError(ErrorCode.PDF_NO_TEXT if fmt is DocumentFormat.PDF else ErrorCode.EMPTY_FILE)
    on_stage(ProcessingStage.EMBEDDING)
    provider = embedder()
    vectors = embed_chunks(chunks, provider)
    identity = EmbeddingIdentity(provider.model, int(vectors.shape[1]))
    return ProcessedDocument(tuple(chunks), document.page_count, vectors, identity)
