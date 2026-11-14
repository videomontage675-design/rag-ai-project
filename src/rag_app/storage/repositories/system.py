"""Read-only queries that describe the state of the knowledge base (``/system/status``)."""

from __future__ import annotations

from dataclasses import dataclass

from rag_app.storage.db import Database


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    """Counts and index metadata read in one consistent pass."""

    schema_version: int
    documents: int
    versions_by_status: dict[str, int]
    active_chunks: int
    conversations: int
    index_embedding_model: str
    index_generation: int


def read_snapshot(db: Database) -> StorageSnapshot:
    """Return current counts and index metadata (one read transaction, consistent view)."""
    with db.connect() as conn:
        conn.execute("BEGIN")  # one snapshot for all reads under WAL
        try:
            schema_version = conn.execute(
                "SELECT COALESCE(MAX(number), 0) FROM schema_migrations"
            ).fetchone()[0]
            documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            by_status = {
                row["status"]: row["n"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS n FROM document_versions GROUP BY status"
                )
            }
            active_chunks = conn.execute("SELECT COUNT(*) FROM active_chunk_vectors").fetchone()[0]
            conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        finally:
            conn.execute("COMMIT")
    return StorageSnapshot(
        schema_version=int(schema_version),
        documents=int(documents),
        versions_by_status={str(k): int(v) for k, v in by_status.items()},
        active_chunks=int(active_chunks),
        conversations=int(conversations),
        index_embedding_model=meta.get("index_embedding_model", ""),
        index_generation=int(meta.get("index_generation", "0")),
    )
