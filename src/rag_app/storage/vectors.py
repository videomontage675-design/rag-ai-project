"""How vectors and index metadata are stored: one place for the byte format and ``meta`` keys.

Vectors are little-endian float32 BLOBs (DESIGN-001 §5.2). The byte order is fixed rather
than native, so a database copied between machines reads back identically.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import VectorSet

FLOAT32_LE = np.dtype("<f4")

BUMP_GENERATION = (
    "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
    " WHERE key = 'index_generation'"
)


@dataclass(frozen=True, slots=True)
class IndexMeta:
    """The model and dimension the stored vectors belong to, and the change counter."""

    model: str
    dim: int
    generation: int


def to_blob(row: npt.NDArray[np.float32]) -> bytes:
    """One vector as stored bytes."""
    return row.astype(FLOAT32_LE, copy=False).tobytes()


def matrix_from_blobs(blobs: Sequence[bytes], dim: int) -> npt.NDArray[np.float32]:
    """Stack stored vectors into a read-only ``(n, dim)`` float32 matrix."""
    if not blobs:
        matrix = np.zeros((0, dim), dtype=np.float32)
    else:
        matrix = np.frombuffer(b"".join(blobs), dtype=FLOAT32_LE).reshape(len(blobs), dim)
        matrix = matrix.astype(np.float32, copy=False)
    matrix.setflags(write=False)
    return matrix


def read_meta(conn: sqlite3.Connection) -> IndexMeta:
    """Read the index metadata row set."""
    meta = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM meta")}
    return IndexMeta(
        model=meta.get("index_embedding_model", ""),
        dim=int(meta.get("index_embedding_dim", "0") or 0),
        generation=int(meta.get("index_generation", "0")),
    )


def write_meta(conn: sqlite3.Connection, model: str, dim: int) -> None:
    """Record which model and dimension the stored vectors belong to."""
    conn.executemany(
        "UPDATE meta SET value = ? WHERE key = ?",
        [(model, "index_embedding_model"), (str(dim), "index_embedding_dim")],
    )


def has_vectors(conn: sqlite3.Connection) -> bool:
    """Whether any vector is stored at all."""
    row = conn.execute("SELECT EXISTS (SELECT 1 FROM chunk_embeddings)").fetchone()
    return bool(row[0])


def claim_index_model(conn: sqlite3.Connection, vectors: VectorSet) -> None:
    """Make sure ``vectors`` may join the index; adopt their model if the index is empty.

    Vectors of different models are never mixed (FR-CFG-05, FR-RET-03): a mismatch means the
    configuration changed and ``rag reindex`` must run first. Call inside the transaction
    that stores the vectors, so the check and the write cannot be separated.

    Raises:
        AppError: ``REINDEX_REQUIRED``.
    """
    meta = read_meta(conn)
    if has_vectors(conn):
        if (meta.model, meta.dim) != (vectors.model, vectors.dim):
            raise AppError(
                ErrorCode.REINDEX_REQUIRED,
                details={"index_model": meta.model, "vectors_model": vectors.model},
            )
        return
    write_meta(conn, vectors.model, vectors.dim)
