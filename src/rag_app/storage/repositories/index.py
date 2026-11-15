"""The vector index as a whole: model checks, re-indexing, and consistency checks.

Every SQL statement about vectors outside a single version's ingestion lives here.
Re-indexing (DESIGN-001 §7.4, FR-CFG-05) works in two steps:

1. batches are embedded and **staged** in ``reindex_staging``, one short transaction each;
2. :meth:`IndexRepository.swap_in` replaces the live vectors in **one** transaction.

Until step 2 commits, the live index is untouched, so an interrupted re-index never leaves a
mix of models behind, and the staged batches are reused when it runs again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import VectorSet
from rag_app.storage.db import Database
from rag_app.storage.vectors import (
    BUMP_GENERATION,
    IndexMeta,
    has_vectors,
    read_meta,
    to_blob,
    write_meta,
)

# Chunks of ready versions, active or not: inactive versions keep their vectors (DD-01).
_READY_CHUNKS = (
    "FROM chunks c JOIN document_versions v ON v.id = c.version_id AND v.status = 'ready'"
)


@dataclass(frozen=True, slots=True)
class PendingChunk:
    """A chunk that has no vector of the target model yet."""

    chunk_id: str
    heading_path: str
    text_normalized: str


@dataclass(frozen=True, slots=True)
class SwapResult:
    """Outcome of :meth:`IndexRepository.swap_in`.

    ``missing`` > 0 means chunks without a target-model vector appeared after they were
    listed (a version finished processing meanwhile); nothing was changed, and the caller
    embeds them and tries again.
    """

    missing: int
    vectors: int
    versions: int


@dataclass(frozen=True, slots=True)
class IndexConsistency:
    """Counts that must all be zero in a consistent index, plus what re-indexing would do."""

    index_model: str
    index_dim: int
    ready_versions: int
    versions_missing_vectors: int
    vectors_of_other_models: int
    vectors_with_wrong_dim: int
    chunk_count_mismatches: int
    staged_vectors: int

    @property
    def problems(self) -> int:
        """Violations of the invariants of DESIGN-001 §5.2 and §7 (never expected)."""
        return (
            self.vectors_of_other_models
            + self.vectors_with_wrong_dim
            + (self.chunk_count_mismatches)
        )


class IndexRepository:
    """Persistence for index-wide operations."""

    def __init__(self, db: Database) -> None:
        """Bind the repository to a database."""
        self._db = db

    # ------------------------------------------------------------------ reads
    def meta(self) -> IndexMeta:
        """The model and dimension of the stored vectors, and the generation counter."""
        with self._db.connect() as conn:
            return read_meta(conn)

    def ensure_compatible(self, model: str) -> None:
        """Refuse early when new vectors of ``model`` could not join the index.

        Called before spending provider quota; the storing transaction checks again
        (:func:`~rag_app.storage.vectors.claim_index_model`).

        Raises:
            AppError: ``REINDEX_REQUIRED``.
        """
        with self._db.connect() as conn:
            meta = read_meta(conn)
            if has_vectors(conn) and meta.model != model:
                raise AppError(
                    ErrorCode.REINDEX_REQUIRED,
                    details={"index_model": meta.model, "vectors_model": model},
                )

    def consistency(self) -> IndexConsistency:
        """Check the invariants of the stored index in one consistent read."""
        with self._db.connect() as conn:
            conn.execute("BEGIN")  # one snapshot for all counts under WAL
            try:
                meta = read_meta(conn)

                def count(sql: str, *params: object) -> int:
                    return int(conn.execute(sql, params).fetchone()[0])

                result = IndexConsistency(
                    index_model=meta.model,
                    index_dim=meta.dim,
                    ready_versions=count(
                        "SELECT COUNT(*) FROM document_versions WHERE status = 'ready'"
                    ),
                    versions_missing_vectors=count(
                        f"SELECT COUNT(DISTINCT c.version_id) {_READY_CHUNKS}"
                        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.model = ?"
                        " WHERE e.chunk_id IS NULL",
                        meta.model,
                    ),
                    vectors_of_other_models=count(
                        "SELECT COUNT(*) FROM chunk_embeddings WHERE model != ?", meta.model
                    ),
                    vectors_with_wrong_dim=count(
                        "SELECT COUNT(*) FROM chunk_embeddings WHERE model = ? AND dim != ?",
                        meta.model,
                        meta.dim,
                    ),
                    chunk_count_mismatches=count(
                        "SELECT COUNT(*) FROM document_versions v WHERE v.status = 'ready'"
                        " AND v.chunk_count IS NOT"
                        " (SELECT COUNT(*) FROM chunks c WHERE c.version_id = v.id)"
                    ),
                    staged_vectors=count("SELECT COUNT(*) FROM reindex_staging"),
                )
            finally:
                conn.execute("COMMIT")
        return result

    # ------------------------------------------------------------------ re-indexing
    def discard_staging_except(self, model: str) -> int:
        """Drop staged vectors of any other model (left by an earlier, abandoned re-index)."""
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM reindex_staging WHERE model != ?", (model,)).rowcount

    def pending_chunks(self, model: str) -> list[PendingChunk]:
        """Chunks of ready versions with neither a live nor a staged vector of ``model``."""
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT c.id, c.heading_path, c.text_normalized {_READY_CHUNKS}"
                " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.model = ?"
                " LEFT JOIN reindex_staging s ON s.chunk_id = c.id AND s.model = ?"
                " WHERE e.chunk_id IS NULL AND s.chunk_id IS NULL"
                " ORDER BY v.uploaded_at, c.version_id, c.seq",
                (model, model),
            ).fetchall()
        return [PendingChunk(r[0], r[1], r[2]) for r in rows]

    def stage(self, chunk_ids: Sequence[str], vectors: VectorSet) -> int:
        """Store one embedded batch in staging; return how many rows were written.

        A chunk deleted while its batch was being embedded is skipped: its row is gone, and
        the foreign key would refuse the insert.
        """
        if len(chunk_ids) != len(vectors):
            msg = f"{len(chunk_ids)} chunk ids but {len(vectors)} vectors"
            raise ValueError(msg)
        placeholders = ",".join("?" * len(chunk_ids))  # one "?" per id: still parameterised
        with self._db.transaction() as conn:
            existing = {
                r[0]
                for r in conn.execute(
                    f"SELECT id FROM chunks WHERE id IN ({placeholders})",  # noqa: S608
                    tuple(chunk_ids),
                )
            }
            rows = [
                (chunk_id, vectors.model, vectors.dim, to_blob(row))
                for chunk_id, row in zip(chunk_ids, vectors.matrix, strict=True)
                if chunk_id in existing
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO reindex_staging (chunk_id, model, dim, vector)"
                " VALUES (?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def swap_in(self, model: str) -> SwapResult:
        """Make ``model`` the index model: replace every vector in one transaction.

        Steps, all-or-nothing: check that every chunk of every ready version has a vector of
        ``model`` (live or staged) and that they share one dimension; delete vectors of other
        models; move the staged vectors in; update versions and ``meta``; bump the generation
        so loaded indexes reload (DESIGN-001 §7.3); clear staging.

        Raises:
            AppError: ``PROVIDER_BAD_RESPONSE`` if the vectors of ``model`` disagree on their
                dimension (the provider changed its output between batches).
        """
        with self._db.transaction() as conn:
            missing = conn.execute(
                f"SELECT COUNT(*) {_READY_CHUNKS}"
                " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.model = ?"
                " LEFT JOIN reindex_staging s ON s.chunk_id = c.id AND s.model = ?"
                " WHERE e.chunk_id IS NULL AND s.chunk_id IS NULL",
                (model, model),
            ).fetchone()[0]
            if missing:
                return SwapResult(missing=missing, vectors=0, versions=0)
            dims = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT dim FROM reindex_staging WHERE model = ?"
                    " UNION SELECT DISTINCT dim FROM chunk_embeddings WHERE model = ?",
                    (model, model),
                )
            }
            if len(dims) > 1:
                raise AppError(ErrorCode.PROVIDER_BAD_RESPONSE, details={"dims": sorted(dims)})
            conn.execute("DELETE FROM chunk_embeddings WHERE model != ?", (model,))
            conn.execute(
                "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, model, dim, vector)"
                " SELECT chunk_id, model, dim, vector FROM reindex_staging WHERE model = ?",
                (model,),
            )
            conn.execute("DELETE FROM reindex_staging")
            vectors = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
            dim = dims.pop() if dims else 0
            versions = conn.execute(
                "UPDATE document_versions SET embedding_model = ?, embedding_dim = ?"
                " WHERE status = 'ready'",
                (model if vectors else None, dim if vectors else None),
            ).rowcount
            write_meta(conn, model if vectors else "", dim)
            conn.execute(BUMP_GENERATION)
        return SwapResult(missing=0, vectors=vectors, versions=versions)
