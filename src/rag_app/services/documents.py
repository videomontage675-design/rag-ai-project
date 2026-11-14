"""DocumentService: the document library use cases (FR-DOC, FR-VER).

Upload order (DESIGN-001 §7.2 in reverse): the file is streamed and validated first, then
given its final name, then the rows are inserted in one transaction. If the insert fails the
file is removed at once; if the process dies in between, the start-up sweep removes it.
Deletion is the mirror image: rows first, files after the commit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import BinaryIO

from rag_app.config.settings import Settings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import DocumentDetail, DocumentFormat, DocumentSummary, VersionInfo
from rag_app.ingestion.validation import decode_markdown, detect_format, safe_display_name
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.repositories.documents import DocumentRepository, NewVersion

logger = logging.getLogger(__name__)

_EXTENSIONS = {DocumentFormat.PDF: ".pdf", DocumentFormat.MARKDOWN: ".md"}


class DocumentService:
    """Upload, list, inspect, activate, retry, and delete documents and their versions."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        files: FileStore,
        on_enqueued: Callable[[], None] = lambda: None,
    ) -> None:
        """Wire the service; ``on_enqueued`` wakes the ingestion worker after an upload."""
        self._repo = DocumentRepository(db)
        self._files = files
        self._max_bytes = settings.limits.max_upload_mb * 1024 * 1024
        self._on_enqueued = on_enqueued

    # ------------------------------------------------------------------ queries
    def list_documents(self) -> list[DocumentSummary]:
        """All documents, most recently updated first."""
        return self._repo.list_documents()

    def get_document(self, document_id: str) -> DocumentDetail:
        """One document with its version history.

        Raises:
            AppError: ``NOT_FOUND``.
        """
        detail = self._repo.get_document(document_id)
        if detail is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return detail

    # ------------------------------------------------------------------ uploads
    def upload_document(self, filename: str, stream: BinaryIO) -> DocumentDetail:
        """Accept a new document; its first version is queued for processing (FR-DOC-01).

        Raises:
            AppError: ``FILE_TOO_LARGE``, ``EMPTY_FILE``, ``UNSUPPORTED_TYPE``,
                ``INVALID_UTF8``, or ``DUPLICATE_CONTENT``.
        """
        version = self._receive(filename, stream)
        try:
            detail = self._repo.create_document(safe_display_name(filename), version)
        except BaseException:
            self._files.delete([version.stored_name])
            raise
        logger.info("document_uploaded", extra={"document_id": detail.id, "format": version.format})
        self._on_enqueued()
        return detail

    def upload_version(self, document_id: str, filename: str, stream: BinaryIO) -> VersionInfo:
        """Add a new version; the current version stays active until it is ready (FR-VER-01/02).

        Raises:
            AppError: as :meth:`upload_document`, plus ``NOT_FOUND``.
        """
        self.get_document(document_id)  # fail fast before reading the upload
        version = self._receive(filename, stream)
        try:
            info = self._repo.add_version(document_id, version)
        except BaseException:
            self._files.delete([version.stored_name])
            raise
        logger.info(
            "version_uploaded",
            extra={"document_id": document_id, "version": info.version_number},
        )
        self._on_enqueued()
        return info

    def _receive(self, filename: str, stream: BinaryIO) -> NewVersion:
        """Stream, validate by content, check duplicates, and give the file its final name."""
        pending = self._files.receive(stream, max_bytes=self._max_bytes)
        try:
            fmt = detect_format(filename, pending.head)
            if fmt is DocumentFormat.MARKDOWN:
                decode_markdown(pending.path.read_bytes())  # reject bad UTF-8 now, not later
            duplicate = self._repo.find_duplicate(pending.sha256)
            if duplicate is not None:
                raise AppError(
                    ErrorCode.DUPLICATE_CONTENT,
                    details={"document_id": duplicate.document_id},
                    document=duplicate.document_name,
                    version=duplicate.version_number,
                )
        except BaseException:
            self._files.discard(pending)
            raise
        stored_name = self._files.accept(pending, _EXTENSIONS[fmt])
        return NewVersion(
            original_filename=filename.replace("\\", "/").rsplit("/", 1)[-1][:255],
            format=fmt,
            size_bytes=pending.size_bytes,
            content_hash=pending.sha256,
            stored_name=stored_name,
        )

    # ------------------------------------------------------------------ changes
    def activate_version(self, document_id: str, version_id: str) -> DocumentDetail:
        """Restore a ready version as the one used for answers (FR-VER-04)."""
        return self._repo.activate_version(document_id, version_id)

    def retry_version(self, document_id: str, version_id: str) -> VersionInfo:
        """Queue a failed version for processing again (FR-DOC-06)."""
        info = self._repo.retry_version(document_id, version_id)
        self._on_enqueued()
        return info

    def delete_document(self, document_id: str) -> None:
        """Delete a document, all its versions, and then their files (FR-DOC-07)."""
        stored = self._repo.delete_document(document_id)
        self._files.delete(stored)
        logger.info("document_deleted", extra={"document_id": document_id})

    def delete_version(self, document_id: str, version_id: str) -> bool:
        """Delete a non-active version (FR-VER-05); return ``True`` if the document went too."""
        stored, document_deleted = self._repo.delete_version(document_id, version_id)
        self._files.delete(stored)
        logger.info(
            "version_deleted",
            extra={"document_id": document_id, "document_deleted": document_deleted},
        )
        return document_deleted

    # ------------------------------------------------------------------ maintenance
    def sweep_orphan_files(self) -> list[str]:
        """Remove upload files that no version references (start-up, DESIGN-001 §7.2)."""
        return self._files.sweep(self._repo.referenced_files())
