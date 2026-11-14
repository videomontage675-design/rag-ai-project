"""System status use case: what the knowledge base contains and whether it is usable."""

from __future__ import annotations

from dataclasses import dataclass

import rag_app
from rag_app.config.settings import Settings
from rag_app.storage.db import Database
from rag_app.storage.repositories.indexing import IndexingRepository
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
    index_embedding_dim: int
    configured_embedding_model: str
    configured_embedding_dim: int | None
    reindex_required: bool
    versions_needing_index: int
    providers: tuple[ProviderInfo, ...]


def get_system_status(settings: Settings, db: Database) -> SystemStatus:
    """Read the current state of the knowledge base and configuration.

    ``reindex_required`` is true when the index holds vectors of another model or dimension
    than configured (FR-RET-03, D-039); an empty index never requires re-indexing.
    ``versions_needing_index`` counts ready versions without current vectors, e.g. those
    processed before Phase 7; ``rag reindex`` embeds them (FR-CFG-05).
    """
    snap = read_snapshot(db)
    configured = settings.providers.embedding.model
    dims = settings.providers.embedding.dimensions
    reindex_required = bool(snap.index_embedding_model) and (
        snap.index_embedding_model != configured
        or (dims is not None and snap.index_embedding_dim != dims)
    )
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
        index_embedding_dim=snap.index_embedding_dim,
        configured_embedding_model=configured,
        configured_embedding_dim=dims,
        reindex_required=reindex_required,
        versions_needing_index=IndexingRepository(db).count_stale(configured, dims),
        providers=tuple(providers),
    )
