"""Documents, versions, chunks, and ingestion jobs: every SQL statement for them lives here.

Each public method is one unit of work in one transaction (DESIGN-001 §7). Methods that change
which chunks are active increment ``meta.index_generation`` in the same transaction, so a
search can never use a stale set of documents (§7.3).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rag_app.core.clock import utc_now_iso
from rag_app.core.errors import AppError, ErrorCode
from rag_app.core.ids import new_id
from rag_app.domain.models import (
    ChunkDraft,
    ClaimedJob,
    DocumentDetail,
    DocumentFormat,
    DocumentSummary,
    EmbeddingIdentity,
    JobStatus,
    ProcessingStage,
    VersionInfo,
    VersionStatus,
)
from rag_app.storage.db import Database


@dataclass(frozen=True, slots=True)
class NewVersion:
    """What the service knows about an accepted upload."""

    original_filename: str
    format: DocumentFormat
    size_bytes: int
    content_hash: str
    stored_name: str


@dataclass(frozen=True, slots=True)
class Duplicate:
    """Where identical content already exists (FR-DOC-04)."""

    document_id: str
    document_name: str
    version_number: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """What start-up recovery did with jobs left ``running`` by a crash (FR-ING-14)."""

    requeued: int
    failed: int


_BUMP_GENERATION = (
    "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
    " WHERE key = 'index_generation'"
)

_VERSION_COLUMNS = """
    v.id, v.version_number, v.status, v.stage, v.original_filename, v.format, v.size_bytes,
    v.page_count, v.chunk_count, v.error_code, v.error_message_ar, v.uploaded_at,
    v.processing_finished_at, (d.active_version_id = v.id) AS is_active
"""


def _insert_vectors(
    conn: sqlite3.Connection,
    chunk_ids: Sequence[str],
    vectors: npt.NDArray[np.float32],
    embedding: EmbeddingIdentity,
) -> None:
    """Store vectors as little-endian float32 BLOBs tagged with model and dimension."""
    conn.executemany(
        "INSERT INTO chunk_embeddings (chunk_id, model, dim, vector) VALUES (?, ?, ?, ?)",
        [
            (chunk_id, embedding.model, embedding.dim, row.astype("<f4").tobytes())
            for chunk_id, row in zip(chunk_ids, vectors, strict=True)
        ],
    )


def _claim_index_identity(conn: sqlite3.Connection, embedding: EmbeddingIdentity) -> None:
    """Record the index's model and dimension when the first vectors arrive.

    Once set, only re-indexing changes them, so a configuration change is detected as
    "re-index required" instead of silently mixing vector spaces (FR-RET-03).
    """
    current = conn.execute("SELECT value FROM meta WHERE key = 'index_embedding_model'").fetchone()
    if current is None or current[0] == "":
        _set_index_identity(conn, embedding)


def _set_index_identity(conn: sqlite3.Connection, embedding: EmbeddingIdentity) -> None:
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'index_embedding_model'", (embedding.model,)
    )
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'index_embedding_dim'", (str(embedding.dim),)
    )


def _version(row: sqlite3.Row) -> VersionInfo:
    return VersionInfo(
        id=row["id"],
        version_number=row["version_number"],
        status=VersionStatus(row["status"]),
        stage=ProcessingStage(row["stage"]) if row["stage"] else None,
        is_active=bool(row["is_active"]),
        original_filename=row["original_filename"],
        format=DocumentFormat(row["format"]),
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        chunk_count=row["chunk_count"],
        error_code=row["error_code"],
        error_message=row["error_message_ar"],
        uploaded_at=row["uploaded_at"],
        processing_finished_at=row["processing_finished_at"],
    )


class DocumentRepository:
    """Persistence for the document library and the ingestion queue."""

    def __init__(self, db: Database) -> None:
        """Bind the repository to a database."""
        self._db = db

    # ------------------------------------------------------------------ reads
    def find_duplicate(self, content_hash: str) -> Duplicate | None:
        """Return the version holding identical content, if any (unique index lookup)."""
        with self._db.connect() as conn:
            return self._find_duplicate(conn, content_hash)

    @staticmethod
    def _find_duplicate(conn: sqlite3.Connection, content_hash: str) -> Duplicate | None:
        row = conn.execute(
            "SELECT d.id, d.display_name, v.version_number FROM document_versions v"
            " JOIN documents d ON d.id = v.document_id WHERE v.content_hash = ?",
            (content_hash,),
        ).fetchone()
        return Duplicate(row[0], row[1], row[2]) if row else None

    def list_documents(self) -> list[DocumentSummary]:
        """All documents, most recently updated first, summarised by their newest version."""
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.display_name, d.updated_at,
                       a.version_number AS active_version,
                       l.version_number AS latest_version, l.status, l.stage, l.format,
                       l.size_bytes,
                       (SELECT COUNT(*) FROM document_versions c WHERE c.document_id = d.id)
                           AS versions
                FROM documents d
                JOIN document_versions l ON l.id = (
                    SELECT id FROM document_versions WHERE document_id = d.id
                    ORDER BY version_number DESC LIMIT 1)
                LEFT JOIN document_versions a ON a.id = d.active_version_id
                ORDER BY d.updated_at DESC, d.display_name
                """
            ).fetchall()
        return [
            DocumentSummary(
                id=r["id"],
                display_name=r["display_name"],
                active_version=r["active_version"],
                latest_version=r["latest_version"],
                versions=r["versions"],
                status=VersionStatus(r["status"]),
                stage=ProcessingStage(r["stage"]) if r["stage"] else None,
                format=DocumentFormat(r["format"]),
                size_bytes=r["size_bytes"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def get_document(self, document_id: str) -> DocumentDetail | None:
        """A document and its version history (newest first), or ``None``."""
        with self._db.connect() as conn:
            return self._get_document(conn, document_id)

    @staticmethod
    def _get_document(conn: sqlite3.Connection, document_id: str) -> DocumentDetail | None:
        doc = conn.execute(
            "SELECT id, display_name, active_version_id, created_at, updated_at"
            " FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if doc is None:
            return None
        versions = conn.execute(
            f"SELECT {_VERSION_COLUMNS} FROM document_versions v"  # noqa: S608  (constant)
            " JOIN documents d ON d.id = v.document_id"
            " WHERE v.document_id = ? ORDER BY v.version_number DESC",
            (document_id,),
        ).fetchall()
        return DocumentDetail(
            id=doc["id"],
            display_name=doc["display_name"],
            active_version_id=doc["active_version_id"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            versions=tuple(_version(v) for v in versions),
        )

    def referenced_files(self) -> set[str]:
        """Stored file names that some version still references (for the orphan sweep)."""
        with self._db.connect() as conn:
            return {r[0] for r in conn.execute("SELECT stored_name FROM document_versions")}

    # ------------------------------------------------------------------ uploads
    def create_document(self, display_name: str, version: NewVersion) -> DocumentDetail:
        """Create a document with its first version and queue its ingestion job.

        Raises:
            AppError: ``DUPLICATE_CONTENT`` if identical content was stored meanwhile.
        """
        now = utc_now_iso()
        document_id = new_id()
        with self._db.transaction() as conn:
            self._refuse_duplicate(conn, version.content_hash)
            conn.execute(
                "INSERT INTO documents (id, display_name, created_at, updated_at,"
                " last_version_number) VALUES (?, ?, ?, ?, 1)",
                (document_id, display_name, now, now),
            )
            self._insert_version(conn, document_id, 1, version, now)
            detail = self._get_document(conn, document_id)
        assert detail is not None  # noqa: S101  (just inserted in this transaction)
        return detail

    def add_version(self, document_id: str, version: NewVersion) -> VersionInfo:
        """Add a new version to an existing document and queue its ingestion job.

        Raises:
            AppError: ``NOT_FOUND`` or ``DUPLICATE_CONTENT``.
        """
        now = utc_now_iso()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT last_version_number FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND)
            self._refuse_duplicate(conn, version.content_hash)
            number = row[0] + 1
            conn.execute(
                "UPDATE documents SET last_version_number = ?, updated_at = ? WHERE id = ?",
                (number, now, document_id),
            )
            version_id = self._insert_version(conn, document_id, number, version, now)
            info = conn.execute(
                f"SELECT {_VERSION_COLUMNS} FROM document_versions v"  # noqa: S608  (constant)
                " JOIN documents d ON d.id = v.document_id WHERE v.id = ?",
                (version_id,),
            ).fetchone()
        return _version(info)

    def _refuse_duplicate(self, conn: sqlite3.Connection, content_hash: str) -> None:
        duplicate = self._find_duplicate(conn, content_hash)
        if duplicate is not None:
            raise AppError(
                ErrorCode.DUPLICATE_CONTENT,
                details={"document_id": duplicate.document_id},
                document=duplicate.document_name,
                version=duplicate.version_number,
            )

    @staticmethod
    def _insert_version(
        conn: sqlite3.Connection, document_id: str, number: int, v: NewVersion, now: str
    ) -> str:
        version_id = new_id()
        conn.execute(
            "INSERT INTO document_versions (id, document_id, version_number, original_filename,"
            " format, size_bytes, content_hash, stored_name, status, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                document_id,
                number,
                v.original_filename,
                v.format.value,
                v.size_bytes,
                v.content_hash,
                v.stored_name,
                VersionStatus.UPLOADED.value,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO ingestion_jobs (id, version_id, kind, status, created_at)"
            " VALUES (?, ?, 'ingest', ?, ?)",
            (new_id(), version_id, JobStatus.QUEUED.value, now),
        )
        return version_id

    # ------------------------------------------------------------------ worker
    def claim_next_job(self) -> ClaimedJob | None:
        """Take the oldest queued job and mark it and its version as running/processing."""
        now = utc_now_iso()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT j.id, j.attempts, v.id AS version_id, v.document_id, v.stored_name,"
                " v.format FROM ingestion_jobs j JOIN document_versions v ON v.id = j.version_id"
                " WHERE j.status = 'queued' ORDER BY j.created_at, j.rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE ingestion_jobs SET status = 'running', attempts = attempts + 1,"
                " started_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.execute(
                "UPDATE document_versions SET status = 'processing', stage = ?,"
                " processing_started_at = ?, error_code = NULL, error_message_ar = NULL"
                " WHERE id = ?",
                (ProcessingStage.VALIDATING.value, now, row["version_id"]),
            )
        return ClaimedJob(
            job_id=row["id"],
            version_id=row["version_id"],
            document_id=row["document_id"],
            stored_name=row["stored_name"],
            format=DocumentFormat(row["format"]),
            attempts=row["attempts"] + 1,
        )

    def set_stage(self, version_id: str, stage: ProcessingStage) -> bool:
        """Record progress; ``False`` means the version was deleted, so the job must stop."""
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE document_versions SET stage = ? WHERE id = ? AND status = 'processing'",
                (stage.value, version_id),
            )
        return cur.rowcount == 1

    def complete_ingestion(
        self,
        job: ClaimedJob,
        chunks: Sequence[ChunkDraft],
        page_count: int | None,
        vectors: npt.NDArray[np.float32],
        embedding: EmbeddingIdentity,
    ) -> bool:
        """Store chunks and their vectors, mark the version ready, and activate it.

        This is the "one commit" rule (DESIGN-001 §7.1): readers see the whole version, with
        its vectors, or nothing. Returns ``False`` without writing if the version was deleted
        meanwhile (DD-02).
        """
        if len(vectors) != len(chunks):
            msg = f"{len(chunks)} chunks but {len(vectors)} vectors"
            raise ValueError(msg)
        chunk_ids = [new_id() for _ in chunks]
        now = utc_now_iso()
        with self._db.transaction() as conn:
            status = conn.execute(
                "SELECT status FROM document_versions WHERE id = ?", (job.version_id,)
            ).fetchone()
            if status is None or status[0] != VersionStatus.PROCESSING:
                return False
            conn.executemany(
                "INSERT INTO chunks (id, version_id, seq, heading_path, text_original,"
                " text_normalized, page_start, page_end, char_start, char_end)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk_id,
                        job.version_id,
                        c.seq,
                        c.heading_path,
                        c.text_original,
                        c.text_normalized,
                        c.page_start,
                        c.page_end,
                        c.char_start,
                        c.char_end,
                    )
                    for chunk_id, c in zip(chunk_ids, chunks, strict=True)
                ],
            )
            _insert_vectors(conn, chunk_ids, vectors, embedding)
            conn.execute(
                "UPDATE document_versions SET status = 'ready', stage = NULL, chunk_count = ?,"
                " page_count = ?, processing_finished_at = ?, embedding_model = ?,"
                " embedding_dim = ? WHERE id = ?",
                (len(chunks), page_count, now, embedding.model, embedding.dim, job.version_id),
            )
            _claim_index_identity(conn, embedding)
            # A new version becomes active only when it is ready (FR-VER-02).
            conn.execute(
                "UPDATE documents SET active_version_id = ?, updated_at = ? WHERE id = ?",
                (job.version_id, now, job.document_id),
            )
            conn.execute(
                "UPDATE ingestion_jobs SET status = 'done', finished_at = ? WHERE id = ?",
                (now, job.job_id),
            )
            conn.execute(_BUMP_GENERATION)
        return True

    def fail_ingestion(self, job: ClaimedJob, code: str, message_ar: str) -> None:
        """Mark the job and version failed; the previously active version stays active."""
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE document_versions SET status = 'failed', stage = NULL, error_code = ?,"
                " error_message_ar = ?, processing_finished_at = ?"
                " WHERE id = ? AND status = 'processing'",
                (code, message_ar, now, job.version_id),
            )
            conn.execute(
                "UPDATE ingestion_jobs SET status = 'failed', error_code = ?, finished_at = ?"
                " WHERE id = ?",
                (code, now, job.job_id),
            )
            conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, job.document_id))

    def recover_interrupted(self, max_attempts: int, message_ar: str) -> RecoveryReport:
        """Re-queue jobs left ``running`` by a crash; fail those out of attempts (FR-ING-14)."""
        now = utc_now_iso()
        with self._db.transaction() as conn:
            stuck = conn.execute(
                "SELECT id, version_id, attempts FROM ingestion_jobs WHERE status = 'running'"
            ).fetchall()
            failed = 0
            for job in stuck:
                if job["attempts"] >= max_attempts:
                    failed += 1
                    conn.execute(
                        "UPDATE ingestion_jobs SET status = 'failed', error_code = ?,"
                        " finished_at = ? WHERE id = ?",
                        (ErrorCode.INTERRUPTED.value, now, job["id"]),
                    )
                    conn.execute(
                        "UPDATE document_versions SET status = 'failed', stage = NULL,"
                        " error_code = ?, error_message_ar = ?, processing_finished_at = ?"
                        " WHERE id = ?",
                        (ErrorCode.INTERRUPTED.value, message_ar, now, job["version_id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE ingestion_jobs SET status = 'queued', started_at = NULL"
                        " WHERE id = ?",
                        (job["id"],),
                    )
                    conn.execute(
                        "UPDATE document_versions SET status = 'uploaded', stage = NULL"
                        " WHERE id = ?",
                        (job["version_id"],),
                    )
        return RecoveryReport(requeued=len(stuck) - failed, failed=failed)

    # ------------------------------------------------------------------ user actions
    def retry_version(self, document_id: str, version_id: str) -> VersionInfo:
        """Queue a failed version again (FR-DOC-06).

        Raises:
            AppError: ``NOT_FOUND`` or ``VERSION_NOT_FAILED``.
        """
        now = utc_now_iso()
        with self._db.transaction() as conn:
            status = self._version_status(conn, document_id, version_id)
            if status is not VersionStatus.FAILED:
                raise AppError(ErrorCode.VERSION_NOT_FAILED)
            conn.execute(
                "UPDATE document_versions SET status = 'uploaded', stage = NULL,"
                " error_code = NULL, error_message_ar = NULL, processing_started_at = NULL,"
                " processing_finished_at = NULL WHERE id = ?",
                (version_id,),
            )
            conn.execute(
                "INSERT INTO ingestion_jobs (id, version_id, kind, status, created_at)"
                " VALUES (?, ?, 'ingest', 'queued', ?)",
                (new_id(), version_id, now),
            )
            conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
            row = conn.execute(
                f"SELECT {_VERSION_COLUMNS} FROM document_versions v"  # noqa: S608  (constant)
                " JOIN documents d ON d.id = v.document_id WHERE v.id = ?",
                (version_id,),
            ).fetchone()
        return _version(row)

    def activate_version(self, document_id: str, version_id: str) -> DocumentDetail:
        """Make a ready version the active one: one ``UPDATE`` (FR-VER-04).

        Raises:
            AppError: ``NOT_FOUND`` or ``VERSION_NOT_READY``.
        """
        now = utc_now_iso()
        with self._db.transaction() as conn:
            if self._version_status(conn, document_id, version_id) is not VersionStatus.READY:
                raise AppError(ErrorCode.VERSION_NOT_READY)
            cur = conn.execute(
                "UPDATE documents SET active_version_id = ?, updated_at = ?"
                " WHERE id = ? AND active_version_id IS NOT ?",
                (version_id, now, document_id, version_id),
            )
            if cur.rowcount:
                conn.execute(_BUMP_GENERATION)
            detail = self._get_document(conn, document_id)
        assert detail is not None  # noqa: S101  (checked in this transaction)
        return detail

    def delete_document(self, document_id: str) -> list[str]:
        """Delete a document and all its versions; return the files to remove afterwards.

        Cascades remove chunks, embeddings, and jobs. A version being processed is cancelled:
        the worker finds its row gone and discards its results (DD-02).

        Raises:
            AppError: ``NOT_FOUND``.
        """
        with self._db.transaction() as conn:
            files = [
                r[0]
                for r in conn.execute(
                    "SELECT stored_name FROM document_versions WHERE document_id = ?",
                    (document_id,),
                )
            ]
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            if cur.rowcount == 0:
                raise AppError(ErrorCode.NOT_FOUND)
            conn.execute(_BUMP_GENERATION)
        return files

    def delete_version(self, document_id: str, version_id: str) -> tuple[list[str], bool]:
        """Delete one non-active version; return its file and whether the document went too.

        Deleting the last remaining version deletes the document, so no empty document is
        ever left in the list.

        Raises:
            AppError: ``NOT_FOUND`` or ``VERSION_IS_ACTIVE``.
        """
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT v.stored_name, (d.active_version_id = v.id) AS is_active"
                " FROM document_versions v JOIN documents d ON d.id = v.document_id"
                " WHERE v.id = ? AND v.document_id = ?",
                (version_id, document_id),
            ).fetchone()
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND)
            if row["is_active"]:
                raise AppError(ErrorCode.VERSION_IS_ACTIVE)
            conn.execute("DELETE FROM document_versions WHERE id = ?", (version_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) FROM document_versions WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            if remaining == 0:
                conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            else:
                conn.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (utc_now_iso(), document_id),
                )
        return [row["stored_name"]], remaining == 0

    @staticmethod
    def _version_status(
        conn: sqlite3.Connection, document_id: str, version_id: str
    ) -> VersionStatus:
        row = conn.execute(
            "SELECT status FROM document_versions WHERE id = ? AND document_id = ?",
            (version_id, document_id),
        ).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return VersionStatus(row[0])
