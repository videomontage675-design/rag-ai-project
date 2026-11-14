"""Forward-only schema migrations from numbered SQL files in ``storage/migrations/``.

Each migration runs in its own transaction together with its ``schema_migrations`` record,
so a failed migration leaves the database exactly as it was (STD-001 §10).
"""

from __future__ import annotations

import logging
import re
from importlib import resources

from rag_app.storage.db import Database

logger = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def available_migrations() -> list[tuple[int, str, str]]:
    """Return ``(number, file name, sql)`` for every packaged migration, in order."""
    found = []
    for entry in resources.files("rag_app.storage.migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    numbers = [number for number, _, _ in found]
    if numbers != list(range(1, len(numbers) + 1)):
        msg = f"migration numbers must be 1..n without gaps, found {numbers}"
        raise RuntimeError(msg)
    return found


def apply_migrations(db: Database) -> list[str]:
    """Apply pending migrations and return the names of those applied (idempotent)."""
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        done = {row[0] for row in conn.execute("SELECT number FROM schema_migrations")}
    applied = []
    for number, name, sql in available_migrations():
        if number in done:
            continue
        with db.transaction() as conn:
            for statement in _split_statements(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (number, name, applied_at)"
                " VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                (number, name),
            )
        logger.info("migration_applied", extra={"migration": name})
        applied.append(name)
    return applied


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into statements.

    ``sqlite3.Connection.executescript`` would commit implicitly and break the per-migration
    transaction, so statements are executed one by one. Migrations therefore must not contain
    triggers or string literals with semicolons (checked by the migration tests).
    """
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]
