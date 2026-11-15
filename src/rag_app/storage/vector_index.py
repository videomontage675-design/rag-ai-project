"""VectorIndex: the active vectors in memory, reloaded whenever the index changes (T-05).

DESIGN-001 §7.3: every transaction that changes the searchable set (a version becomes ready,
a version is activated, a document is deleted, a re-index swaps vectors) increments
``meta.index_generation``. :meth:`VectorIndex.current` reads that counter, a one-row read,
and reloads the matrix only when it changed. No caller can therefore use a stale set of
documents, and an unchanged index costs no reload.

Only rows of the ``active_chunk_vectors`` view are loaded: chunks of the **active, ready**
version of each document (FR-RET-04, FR-VER-02). The similarity search itself is Phase 8
(D-039).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rag_app.core.errors import AppError, ErrorCode
from rag_app.storage.db import Database
from rag_app.storage.vectors import matrix_from_blobs, read_meta

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, eq=False)
class IndexSnapshot:
    """The searchable vectors at one generation; immutable, so it can be shared by threads.

    Row ``i`` of ``vectors`` belongs to ``chunk_ids[i]`` and ``document_ids[i]``. Rows are
    L2-normalized, so ``vectors @ query`` gives cosine similarities.
    """

    generation: int
    model: str
    dim: int
    chunk_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    vectors: npt.NDArray[np.float32]

    def __len__(self) -> int:
        """Number of searchable chunks."""
        return len(self.chunk_ids)


class VectorIndex:
    """Thread-safe cache of the active vectors, keyed by ``index_generation``."""

    def __init__(self, db: Database) -> None:
        """Bind the index to a database; nothing is loaded until first use."""
        self._db = db
        self._lock = threading.Lock()
        self._snapshot: IndexSnapshot | None = None

    def current(self) -> IndexSnapshot:
        """Return the active vectors, reloading them if the index changed since last time.

        Raises:
            AppError: ``REINDEX_REQUIRED`` if stored vectors disagree with the index model,
                which the write paths prevent; it signals a database edited by hand.
        """
        generation = self._generation()
        snapshot = self._snapshot
        if snapshot is not None and snapshot.generation == generation:
            return snapshot
        with self._lock:
            # Another thread may have reloaded while this one waited for the lock.
            if self._snapshot is None or self._snapshot.generation != generation:
                self._snapshot = self._load()
            return self._snapshot

    def _generation(self) -> int:
        with self._db.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'index_generation'").fetchone()
        return int(row[0])

    def _load(self) -> IndexSnapshot:
        """Read the counter and the rows in one transaction, so they describe the same state."""
        with self._db.connect() as conn:
            conn.execute("BEGIN")
            try:
                meta = read_meta(conn)
                rows = conn.execute(
                    "SELECT chunk_id, document_id, model, dim, vector FROM active_chunk_vectors"
                    " ORDER BY document_id, chunk_id"
                ).fetchall()
            finally:
                conn.execute("COMMIT")
        if any(r["model"] != meta.model or r["dim"] != meta.dim for r in rows):
            raise AppError(ErrorCode.REINDEX_REQUIRED, details={"index_model": meta.model})
        snapshot = IndexSnapshot(
            generation=meta.generation,
            model=meta.model,
            dim=meta.dim,
            chunk_ids=tuple(r["chunk_id"] for r in rows),
            document_ids=tuple(r["document_id"] for r in rows),
            vectors=matrix_from_blobs([r["vector"] for r in rows], meta.dim),
        )
        logger.info(
            "vector_index_loaded",
            extra={"generation": snapshot.generation, "chunks": len(snapshot), "dim": meta.dim},
        )
        return snapshot
