"""API response schemas. Pydantic lives here, at the boundary, never in the pipeline."""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from rag_app.domain.models import DocumentDetail, DocumentSummary, VersionInfo


class HealthResponse(BaseModel):
    """Liveness probe result."""

    status: str
    version: str


class ProviderOut(BaseModel):
    """A configured model provider (no secrets)."""

    role: str
    model: str
    fallback_model: str | None


class SystemStatusResponse(BaseModel):
    """Knowledge-base counts, index state, and configured providers."""

    app_version: str
    schema_version: int
    documents: int
    versions_by_status: dict[str, int]
    active_chunks: int
    conversations: int
    index_embedding_model: str
    index_embedding_dim: int
    configured_embedding_model: str
    configured_embedding_dim: int | None
    reindex_required: bool
    versions_needing_index: int
    providers: list[ProviderOut]


class ErrorInfo(BaseModel):
    """Why a version failed, as shown to the user."""

    code: str
    message: str


class VersionOut(BaseModel):
    """One version in a document's history (DESIGN-001 §11.1 ``VersionInfo``)."""

    id: str
    version_number: int
    status: str
    stage: str | None
    is_active: bool
    original_filename: str
    format: str
    size_bytes: int
    page_count: int | None
    chunk_count: int | None
    error: ErrorInfo | None
    uploaded_at: str
    processing_finished_at: str | None

    @classmethod
    def of(cls, v: VersionInfo) -> VersionOut:
        """Convert the domain record."""
        error = (
            ErrorInfo(code=v.error_code, message=v.error_message or "") if v.error_code else None
        )
        return cls(
            id=v.id,
            version_number=v.version_number,
            status=v.status,
            stage=v.stage,
            is_active=v.is_active,
            original_filename=v.original_filename,
            format=v.format,
            size_bytes=v.size_bytes,
            page_count=v.page_count,
            chunk_count=v.chunk_count,
            error=error,
            uploaded_at=v.uploaded_at,
            processing_finished_at=v.processing_finished_at,
        )


class DocumentSummaryOut(BaseModel):
    """One row of the document list; status, format, and size are the newest version's."""

    id: str
    display_name: str
    active_version: int | None
    latest_version: int
    versions: int
    status: str
    stage: str | None
    format: str
    size_bytes: int
    updated_at: str

    @classmethod
    def of(cls, d: DocumentSummary) -> DocumentSummaryOut:
        """Convert the domain record."""
        return cls.model_validate(asdict(d))


class DocumentDetailOut(BaseModel):
    """A document with its version history, newest first."""

    id: str
    display_name: str
    active_version_id: str | None
    is_processing: bool
    created_at: str
    updated_at: str
    versions: list[VersionOut]

    @classmethod
    def of(cls, d: DocumentDetail) -> DocumentDetailOut:
        """Convert the domain record."""
        return cls(
            id=d.id,
            display_name=d.display_name,
            active_version_id=d.active_version_id,
            is_processing=d.is_processing,
            created_at=d.created_at,
            updated_at=d.updated_at,
            versions=[VersionOut.of(v) for v in d.versions],
        )
