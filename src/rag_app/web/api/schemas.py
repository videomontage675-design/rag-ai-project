"""API response schemas. Pydantic lives here, at the boundary, never in the pipeline."""

from __future__ import annotations

from pydantic import BaseModel


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
    configured_embedding_model: str
    reindex_required: bool
    providers: list[ProviderOut]
