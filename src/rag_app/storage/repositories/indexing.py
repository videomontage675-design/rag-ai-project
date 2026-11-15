"""Re-indexing queries (FR-CFG-05, DESIGN-001 §7.4): find stale versions, swap vectors at once."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rag_app.domain.models import EmbeddingIdentity
from rag_app.storage.db import Database
from rag_app.storage.repositories.documents import (
    _BUMP_GENERATION,
    _insert_vectors,
    _set_index_identity,
)

# A ready version is stale when it has no vectors or vectors of another model or size.
_STALE = (
    "status = 'ready' AND (embedding_model IS NULL OR embedding_model != ?"
    " OR (? IS NOT NULL AND embedding_dim != ?))"
)


@dataclass(frozen=True, slots=True)
class VersionChunks:
    """The chunks of one version, in order, as needed for embedding."""

    version_id: str
    chunk_ids: tuple[str, ...]
    heading_paths: tuple[str, ...]
    texts_normalized: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddedVersion:
    """New vectors for one version; ``vectors[i]`` belongs to ``chunk_ids[i]``."""

    version_id: str
    chunk_ids: tuple[str, ...]
    vectors: npt.NDArray[np.float32]


class IndexingRepository:
    """Reads what needs embedding and replaces vectors in one transaction."""

    def __init__(self, db: Database) -> None:
        """Bind the repository to a database."""
        self._db = db

    def count_stale(self, model: str, dim: int | None) -> int:
        """Ready versions (active or not, DD-01) whose vectors are missing or outdated."""
        with self._db.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM document_versions WHERE {_STALE}",  # noqa: S608  (constant)
                (model, dim, dim),
            ).fetchone()
        return int(row[0])

    def stale_versions(self, model: str, dim: int | None) -> list[VersionChunks]:
        """Chunks of every stale ready version, oldest upload first."""
        with self._db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    f"SELECT id FROM document_versions WHERE {_STALE}"  # noqa: S608  (constant)
                    " ORDER BY uploaded_at",
                    (model, dim, dim),
                )
            ]
            out = []
            for version_id in ids:
                rows = conn.execute(
                    "SELECT id, heading_path, text_normalized FROM chunks"
                    " WHERE version_id = ? ORDER BY seq",
                    (version_id,),
                ).fetchall()
                out.append(
                    VersionChunks(
                        version_id,
                        tuple(r[0] for r in rows),
                        tuple(r[1] for r in rows),
                        tuple(r[2] for r in rows),
                    )
                )
        return out

    def replace_vectors(
        self, embedded: Sequence[EmbeddedVersion], identity: EmbeddingIdentity
    ) -> int:
        """Swap in all new vectors and the new index identity in **one** transaction.

        Until it commits, searches use the old vectors; if it fails, nothing changes
        (FR-CFG-05: vectors of two models are never mixed in the index). Versions deleted
        while embedding are skipped. Returns the number of versions updated.
        """
        updated = 0
        with self._db.transaction() as conn:
            for item in embedded:
                current = conn.execute(
                    "SELECT id FROM chunks WHERE version_id = ? ORDER BY seq", (item.version_id,)
                ).fetchall()
                if tuple(r[0] for r in current) != item.chunk_ids:
                    continue  # deleted (or changed) meanwhile
                conn.execute(
                    "DELETE FROM chunk_embeddings WHERE chunk_id IN"
                    " (SELECT id FROM chunks WHERE version_id = ?)",
                    (item.version_id,),
                )
                _insert_vectors(conn, item.chunk_ids, item.vectors, identity)
                conn.execute(
                    "UPDATE document_versions SET embedding_model = ?, embedding_dim = ?"
                    " WHERE id = ?",
                    (identity.model, identity.dim, item.version_id),
                )
                updated += 1
            _set_index_identity(conn, identity)
            conn.execute(_BUMP_GENERATION)
        return updated
