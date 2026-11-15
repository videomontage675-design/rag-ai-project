"""System status use case: what the knowledge base contains and whether it is usable."""

from __future__ import annotations

from dataclasses import dataclass

import rag_app
from rag_app.config.settings import Settings
from rag_app.storage.db import Database
from rag_app.storage.repositories.index import IndexRepository
from rag_app.storage.repositories.system import read_snapshot


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Public description of a configured provider (no keys, no key variable names)."""

    role: str
    model: str
    fallback_model: str | None


@dataclass(frozen=True, slots=True)
class SystemStatus:
    """Snapshot returned by ``GET /api/v1/system/status``."""

    app_version: str
    schema_version: int
    documents: int
    versions_by_status: dict[str, int]
    active_chunks: int
    conversations: int
    index_embedding_model: str
    configured_embedding_model: str
    reindex_required: bool
    versions_missing_vectors: int
    providers: tuple[ProviderInfo, ...]


def get_system_status(settings: Settings, db: Database) -> SystemStatus:
    """Read the current state of the knowledge base and configuration.

    ``reindex_required`` is true when vectors exist for a different embedding model than the
    configured one (FR-RET-03); an empty index never requires re-indexing.
    ``versions_missing_vectors`` counts ready versions that retrieval cannot see because they
    have no vectors of the index model (processed before Phase 7); ``rag reindex`` fixes both.
    """
    snap = read_snapshot(db)
    missing = IndexRepository(db).consistency().versions_missing_vectors
    configured = settings.providers.embedding.model
    reindex_required = bool(snap.index_embedding_model) and snap.index_embedding_model != configured
    providers = [
        ProviderInfo("embedding", settings.providers.embedding.model, None),
        ProviderInfo("chat", settings.providers.chat.model, settings.providers.chat.fallback_model),
    ]
    return SystemStatus(
        app_version=rag_app.__version__,
        schema_version=snap.schema_version,
        documents=snap.documents,
        versions_by_status=snap.versions_by_status,
        active_chunks=snap.active_chunks,
        conversations=snap.conversations,
        index_embedding_model=snap.index_embedding_model,
        configured_embedding_model=configured,
        reindex_required=reindex_required,
        versions_missing_vectors=missing,
        providers=tuple(providers),
    )
