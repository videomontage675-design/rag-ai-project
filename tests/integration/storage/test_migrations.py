import sqlite3

import pytest

from rag_app.storage.db import Database
from rag_app.storage.migrate import apply_migrations, available_migrations

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "meta",
    "documents",
    "document_versions",
    "chunks",
    "chunk_embeddings",
    "ingestion_jobs",
    "conversations",
    "messages",
    "citations",
    "schema_migrations",
}


def _names(conn: sqlite3.Connection, kind: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def test_migrations_create_schema_and_are_idempotent(db: Database) -> None:
    assert apply_migrations(db) == []
    with db.connect() as conn:
        assert _names(conn, "table") >= EXPECTED_TABLES
        assert "active_chunk_vectors" in _names(conn, "view")


def test_connection_pragmas_are_applied(db: Database) -> None:
    with db.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migration_files_have_no_semicolons_in_literals_or_triggers() -> None:
    for _, name, sql in available_migrations():
        assert "CREATE TRIGGER" not in sql.upper(), name
        assert "';'" not in sql, name


def _plan(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> str:
    return " | ".join(r["detail"] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))


@pytest.mark.parametrize(
    ("query", "params", "expected_index"),
    [
        (
            "SELECT id FROM document_versions WHERE content_hash = ?",
            ("h",),
            "ux_versions_content_hash",
        ),
        (
            "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_number",
            ("d",),
            "ux_versions_document_number",
        ),
        (
            "SELECT id FROM ingestion_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1",
            (),
            "ix_jobs_status_created",
        ),
        (
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq",
            ("c",),
            "ux_messages_conversation_seq",
        ),
        (
            "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 50",
            (),
            "ix_conversations_updated",
        ),
        ("SELECT * FROM citations WHERE message_id = ?", ("m",), "ix_citations_message"),
    ],
)
def test_hot_queries_use_their_index(
    db: Database, query: str, params: tuple[object, ...], expected_index: str
) -> None:
    with db.connect() as conn:
        assert expected_index in _plan(conn, query, params)


def test_active_vector_view_does_not_scan_chunks(db: Database) -> None:
    with db.connect() as conn:
        plan = _plan(conn, "SELECT chunk_id, vector FROM active_chunk_vectors")

    assert "SCAN c" not in plan and "SCAN chunks" not in plan, plan
    assert "ux_chunks_version_seq" in plan


def _seed(conn: sqlite3.Connection, *, status: str = "ready", active: bool = True) -> None:
    conn.execute("INSERT INTO documents VALUES ('d1', 'doc', NULL, 't', 't')")
    conn.execute(
        "INSERT INTO document_versions (id, document_id, version_number, original_filename, format,"
        " size_bytes, content_hash, stored_name, status, uploaded_at)"
        " VALUES ('v1', 'd1', 1, 'a.md', 'markdown', 10, 'h1', 's1', ?, 't')",
        (status,),
    )
    conn.execute(
        "INSERT INTO chunks (id, version_id, seq, text_original, text_normalized,"
        " char_start, char_end) VALUES ('c1', 'v1', 0, 'x', 'x', 0, 1)"
    )
    conn.execute("INSERT INTO chunk_embeddings VALUES ('c1', 'm', 2, ?)", (b"\x00" * 8,))
    if active:
        conn.execute("UPDATE documents SET active_version_id = 'v1' WHERE id = 'd1'")


def test_view_shows_only_ready_active_versions(db: Database) -> None:
    with db.transaction() as conn:
        _seed(conn, status="processing")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_chunk_vectors").fetchone()[0] == 0
    with db.transaction() as conn:
        conn.execute("UPDATE document_versions SET status = 'ready'")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM active_chunk_vectors").fetchone()[0] == 1


def test_deleting_document_cascades_and_leaves_no_orphans(db: Database) -> None:
    with db.transaction() as conn:
        _seed(conn)
    with db.transaction() as conn:
        conn.execute("DELETE FROM documents WHERE id = 'd1'")
    with db.connect() as conn:
        for table in ("document_versions", "chunks", "chunk_embeddings"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0  # noqa: S608


def test_failed_transaction_rolls_back_everything(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        _seed(conn)
        conn.execute("INSERT INTO documents VALUES ('d1', 'dup', NULL, 't', 't')")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_embedding_vector_length_must_match_dimension(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        _seed(conn)
        conn.execute("UPDATE chunk_embeddings SET vector = ? WHERE chunk_id = 'c1'", (b"\x00" * 4,))
