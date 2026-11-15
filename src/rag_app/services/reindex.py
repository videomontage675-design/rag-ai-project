"""Re-indexing: give every ready version vectors of the configured embedding model.

FR-CFG-05, DESIGN-001 §7.4, DD-05. Two models are never mixed in the live index.

Run by ``rag reindex`` while the app is stopped. It is needed when:

* the configured embedding model changed (questions are refused until it runs, FR-RET-03);
* versions became ready before embeddings existed (Phase 6, D-034), so they have no vectors.

Only chunks lacking a vector of the configured model are embedded, so a re-index after an
interruption, or with nothing to do, spends no provider quota on work already done.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from rag_app.ingestion.embedding import embed_texts, embedding_text
from rag_app.providers.ports import EmbeddingProvider
from rag_app.storage.db import Database
from rag_app.storage.repositories.index import IndexConsistency, IndexRepository

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class ReindexPlan:
    """What a re-index would do, read before any provider call."""

    model: str
    index_model: str
    chunks_to_embed: int
    staged_reusable: int
    up_to_date: bool


@dataclass(frozen=True, slots=True)
class ReindexReport:
    """What a re-index did."""

    model: str
    dim: int
    embedded: int
    vectors: int
    versions: int
    completed: bool


class ReindexService:
    """Embeds missing vectors into staging, then swaps them in with one transaction."""

    def __init__(
        self,
        db: Database,
        embedder: EmbeddingProvider,
        *,
        batch_size: int,
        max_passes: int = 3,
    ) -> None:
        """``embedder`` should already throttle and retry (``providers.resilience``)."""
        self._repo = IndexRepository(db)
        self._embedder = embedder
        self._batch_size = batch_size
        self._max_passes = max_passes

    def plan(self) -> ReindexPlan:
        """Describe the work without calling the provider."""
        model = self._embedder.model
        state: IndexConsistency = self._repo.consistency()
        pending = len(self._repo.pending_chunks(model))
        up_to_date = (
            pending == 0
            # An empty model means no vector is stored at all: an empty index is current.
            and state.index_model in (model, "")
            and state.vectors_of_other_models == 0
            and state.staged_vectors == 0
        )
        return ReindexPlan(
            model=model,
            index_model=state.index_model,
            chunks_to_embed=pending,
            staged_reusable=state.staged_vectors,
            up_to_date=up_to_date,
        )

    def run(self, on_progress: Progress = lambda _done, _total: None) -> ReindexReport:
        """Embed what is missing, then swap it in.

        If versions keep becoming ready while it runs (the app was not stopped), each pass
        embeds the newcomers; after ``max_passes`` it gives up without changing the live
        index, and ``completed`` is ``False``.

        Raises:
            ProviderError: the provider failed after its retries. Batches staged so far are
                kept and reused by the next run.
        """
        model = self._embedder.model
        if discarded := self._repo.discard_staging_except(model):
            logger.info("reindex_staging_discarded", extra={"vectors": discarded})
        embedded = 0
        dim = 0
        for _ in range(self._max_passes):
            pending = self._repo.pending_chunks(model)
            for start in range(0, len(pending), self._batch_size):
                on_progress(start, len(pending))
                batch = pending[start : start + self._batch_size]
                vectors = embed_texts(
                    [embedding_text(c.heading_path, c.text_normalized) for c in batch],
                    self._embedder,
                    batch_size=self._batch_size,
                )
                dim = vectors.dim
                embedded += self._repo.stage([c.chunk_id for c in batch], vectors)
            on_progress(len(pending), len(pending))
            result = self._repo.swap_in(model)
            if result.missing == 0:
                meta = self._repo.meta()
                logger.info(
                    "reindex_completed",
                    extra={"model": model, "embedded": embedded, "vectors": result.vectors},
                )
                return ReindexReport(
                    model=model,
                    dim=meta.dim or dim,
                    embedded=embedded,
                    vectors=result.vectors,
                    versions=result.versions,
                    completed=True,
                )
        logger.warning("reindex_incomplete", extra={"model": model, "embedded": embedded})
        return ReindexReport(
            model=model, dim=dim, embedded=embedded, vectors=0, versions=0, completed=False
        )
