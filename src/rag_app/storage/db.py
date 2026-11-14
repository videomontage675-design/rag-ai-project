"""SQLite connection management with the pragmas and transaction discipline of DESIGN-001 §7.

Connections are short-lived (one per unit of work). SQLite in WAL mode lets the web requests
read while the ingestion worker writes, and short transactions keep writer contention low.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Applied on every connection. WAL + NORMAL is crash-safe for the database file and much
# faster than FULL; foreign keys make ON DELETE CASCADE / SET NULL actually happen.
_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA cache_size = -20000",
)


class Database:
    """Factory for configured SQLite connections to one database file."""

    def __init__(self, path: Path) -> None:
        """Remember the database path; the parent folder is created on first connection."""
        self.path = path

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: we issue BEGIN/COMMIT ourselves, so transaction boundaries
        # are explicit and visible in the code (STD-001 §10).
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection for reads; it is always closed afterwards."""
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside ``BEGIN IMMEDIATE``; commit on success, roll back on error.

        ``IMMEDIATE`` takes the write lock at the start, so two writers never deadlock halfway
        through a multi-row change (DESIGN-001 §7.1).
        """
        conn = self._open()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()
