"""Re-indexing use case (FR-CFG-05, DD-05): embed every stale version, then swap at once.

Used by ``rag reindex`` after the embedding model or dimension changes, and to embed the
versions that Phase 6 stored without vectors (D-034). All new vectors are held in memory
(61 MB at 20,000 chunks × 768 dimensions) and written in one transaction, so an interrupted
re-index leaves the previous index fully intact.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from rag_app.config.settings import Settings
from rag_app.domain.models import EmbeddingIdentity
from rag_app.ingestion.embedding import embedding_text
from rag_app.providers.ports import EmbeddingProvider
from rag_app.storage.db import Database
from rag_app.storage.repositories.indexing import EmbeddedVersion, IndexingRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReindexReport:
    """What a re-index did."""

    versions: int
    chunks: int
    identity: EmbeddingIdentity | None


class IndexingService:
    """Finds versions whose vectors are missing or outdated and re-embeds them."""

    def __init__(
        self, settings: Settings, db: Database, embedder: Callable[[], EmbeddingProvider]
    ) -> None:
        """Wire the service; the embedder is created only when there is work to do."""
        self._config = settings.providers.embedding
        self._repo = IndexingRepository(db)
        self._embedder = embedder

    def pending_versions(self) -> int:
        """Ready versions that a re-index would embed."""
        return self._repo.count_stale(self._config.model, self._config.dimensions)

    def reindex(
        self, progress: Callable[[int, int], None] = lambda _done, _total: None
    ) -> ReindexReport:
        """Embed all stale versions with the configured provider, then commit once.

        Raises:
            AppError: ``PROVIDER_*`` if embedding fails; the existing index is untouched.
        """
        stale = self._repo.stale_versions(self._config.model, self._config.dimensions)
        if not stale:
            return ReindexReport(0, 0, None)
        provider = self._embedder()
        embedded: list[EmbeddedVersion] = []
        for done, version in enumerate(stale, start=1):
            texts = [
                embedding_text(h, t)
                for h, t in zip(version.heading_paths, version.texts_normalized, strict=True)
            ]
            vectors = provider.embed(texts, "document")
            embedded.append(EmbeddedVersion(version.version_id, version.chunk_ids, vectors))
            progress(done, len(stale))
        identity = EmbeddingIdentity(provider.model, int(embedded[0].vectors.shape[1]))
        updated = self._repo.replace_vectors(embedded, identity)
        chunks = sum(len(e.chunk_ids) for e in embedded)
        logger.info("reindex_done", extra={"versions": updated, "chunks": chunks})
        return ReindexReport(updated, chunks, identity)
