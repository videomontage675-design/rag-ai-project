"""The worker thread lifecycle and its handling of unexpected errors."""

from __future__ import annotations

import io
import time

import pytest

from rag_app.config.settings import Settings
from rag_app.core.errors import ErrorCode
from rag_app.domain.models import VersionStatus
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore

pytestmark = pytest.mark.integration


def _wait_for(predicate: object, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.02)
    return False


def test_background_thread_processes_uploads_and_stops(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    worker.start()
    worker.start()  # idempotent
    try:
        doc_id = documents.upload_document("a.md", io.BytesIO("# أ\n\nنص.\n".encode())).id
        # on_enqueued wakes the worker, so it does not wait for the poll interval
        assert _wait_for(lambda: documents.get_document(doc_id).active is not None)
    finally:
        worker.stop(timeout=5)
    assert worker._thread is None


def test_unexpected_error_fails_the_version_with_a_generic_message(
    settings: Settings, db: Database, files: FileStore, documents: DocumentService
) -> None:
    def broken_poppler() -> object:
        raise RuntimeError("bug")

    worker = IngestionWorker(settings, db, files, poppler=broken_poppler)  # type: ignore[arg-type]
    doc_id = documents.upload_document("a.pdf", io.BytesIO(b"%PDF-1.7 x")).id

    worker.run_until_idle()

    (version,) = documents.get_document(doc_id).versions
    assert version.status is VersionStatus.FAILED
    assert version.error_code == ErrorCode.INTERNAL_ERROR.value
    assert "bug" not in (version.error_message or "")  # internals never reach the user


def test_loop_survives_a_failing_iteration(
    worker: IngestionWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def flaky() -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return False

    monkeypatch.setattr(worker, "run_once", flaky)
    worker.start()
    try:
        worker.wake()
        assert _wait_for(lambda: len(calls) >= 2)
    finally:
        worker.stop(timeout=5)
