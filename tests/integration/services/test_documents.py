"""DocumentService + DocumentRepository + IngestionWorker against a real SQLite file."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from rag_app.config.settings import Settings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import ProcessingStage, VersionStatus
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from support import pdfs

pytestmark = pytest.mark.integration

GUIDE = "# دليل المواعيد\n\n## إنشاء موعد\n\nيُنشأ الموعد من شاشة التقويم.\n".encode()
GUIDE_V2 = GUIDE + "\n## إلغاء موعد\n\nيُلغى الموعد من بطاقة الموعد.\n".encode()
CORPUS_PDF = Path(__file__).resolve().parents[3] / "data/sample_corpus/pdf/05_privacy_security.pdf"


def _generation(db: Database) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'index_generation'").fetchone()
    return int(row[0])


def _count(db: Database, table: str) -> int:
    with db.connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608


def _upload(documents: DocumentService, data: bytes = GUIDE, name: str = "دليل.md") -> str:
    return documents.upload_document(name, io.BytesIO(data)).id


# ------------------------------------------------------------------ upload and processing
def test_upload_queues_then_worker_makes_it_ready_and_active(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    detail = documents.upload_document("C:\\docs\\دليل المواعيد.md", io.BytesIO(GUIDE))

    assert detail.display_name == "دليل المواعيد"
    (version,) = detail.versions
    assert version.status is VersionStatus.UPLOADED
    assert version.original_filename == "دليل المواعيد.md"
    assert detail.active is None and detail.is_processing

    generation = _generation(db)
    assert worker.run_until_idle() == 1

    done = documents.get_document(detail.id)
    assert done.active is not None
    assert done.active.status is VersionStatus.READY
    assert done.active.chunk_count == 1
    assert done.active.stage is None
    assert not done.is_processing
    assert _generation(db) == generation + 1
    with db.connect() as conn:
        row = conn.execute("SELECT heading_path, text_original FROM chunks").fetchone()
    assert tuple(row) == ("دليل المواعيد › إنشاء موعد", "يُنشأ الموعد من شاشة التقويم.")


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="Poppler not installed")
def test_pdf_upload_is_processed_with_pages(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents, CORPUS_PDF.read_bytes(), "privacy.pdf")

    worker.run_until_idle()

    active = documents.get_document(doc_id).active
    assert active is not None
    assert active.page_count == 3
    assert active.chunk_count is not None and active.chunk_count > 5


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("a.docx", b"PK\x03\x04", ErrorCode.UNSUPPORTED_TYPE),
        ("a.pdf", b"# markdown", ErrorCode.UNSUPPORTED_TYPE),
        ("a.md", b"\xff\xfe broken", ErrorCode.INVALID_UTF8),
        ("a.md", b"", ErrorCode.EMPTY_FILE),
    ],
)
def test_invalid_uploads_are_rejected_and_leave_nothing(
    documents: DocumentService,
    files: FileStore,
    db: Database,
    name: str,
    data: bytes,
    code: ErrorCode,
) -> None:
    with pytest.raises(AppError) as info:
        documents.upload_document(name, io.BytesIO(data))

    assert info.value.code is code
    assert _count(db, "documents") == 0
    assert not files.root.exists() or list(files.root.iterdir()) == []


def test_oversized_upload_is_rejected(
    settings_factory_small_limit: DocumentService, files: FileStore
) -> None:
    with pytest.raises(AppError) as info:
        settings_factory_small_limit.upload_document("a.md", io.BytesIO(b"x" * (1024 * 1024 + 1)))

    assert info.value.code is ErrorCode.FILE_TOO_LARGE
    assert list(files.root.iterdir()) == []


@pytest.fixture
def settings_factory_small_limit(
    documents: DocumentService, monkeypatch: pytest.MonkeyPatch
) -> DocumentService:
    monkeypatch.setattr(documents, "_max_bytes", 1024 * 1024)
    return documents


def test_duplicate_content_is_rejected_with_a_pointer(
    documents: DocumentService, files: FileStore
) -> None:
    first = _upload(documents)

    with pytest.raises(AppError) as info:
        documents.upload_document("copy.md", io.BytesIO(GUIDE))

    assert info.value.code is ErrorCode.DUPLICATE_CONTENT
    assert info.value.details == {"document_id": first}
    assert "دليل" in info.value.message_ar and "1" in info.value.message_ar
    assert len(list(files.root.iterdir())) == 1


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="Poppler not installed")
@pytest.mark.parametrize(
    ("factory", "code"),
    [(pdfs.blank_pdf, ErrorCode.PDF_NO_TEXT), (pdfs.encrypted_pdf, ErrorCode.PDF_ENCRYPTED)],
)
def test_unprocessable_pdf_fails_with_arabic_message(
    documents: DocumentService, worker: IngestionWorker, factory: object, code: ErrorCode
) -> None:
    doc_id = _upload(documents, factory(), "scan.pdf")  # type: ignore[operator]

    worker.run_until_idle()

    (version,) = documents.get_document(doc_id).versions
    assert version.status is VersionStatus.FAILED
    assert version.error_code == code.value
    assert version.error_message and "PDF" in version.error_message


# ------------------------------------------------------------------ versions
def test_new_version_activates_only_when_ready(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()
    v1 = documents.get_document(doc_id).versions[0]

    v2 = documents.upload_version(doc_id, "دليل-2.md", io.BytesIO(GUIDE_V2))

    assert v2.version_number == 2
    assert documents.get_document(doc_id).active_version_id == v1.id  # v1 still answers
    worker.run_until_idle()
    detail = documents.get_document(doc_id)
    assert detail.active_version_id == v2.id
    assert [v.version_number for v in detail.versions] == [2, 1]
    assert documents.list_documents()[0].active_version == 2


def test_failed_new_version_keeps_previous_active(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()
    v1_id = documents.get_document(doc_id).active_version_id

    documents.upload_version(doc_id, "only-headings.md", io.BytesIO("# عنوان\n".encode()))
    worker.run_until_idle()

    detail = documents.get_document(doc_id)
    assert detail.active_version_id == v1_id
    assert detail.versions[0].status is VersionStatus.FAILED
    assert documents.list_documents()[0].status is VersionStatus.FAILED


def test_activate_restores_an_older_ready_version(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    doc_id = _upload(documents)
    documents.upload_version(doc_id, "v2.md", io.BytesIO(GUIDE_V2))
    worker.run_until_idle()
    v1 = documents.get_document(doc_id).versions[1]
    generation = _generation(db)

    detail = documents.activate_version(doc_id, v1.id)

    assert detail.active_version_id == v1.id
    assert _generation(db) == generation + 1
    documents.activate_version(doc_id, v1.id)  # already active: no change, no new generation
    assert _generation(db) == generation + 1


def test_activate_refuses_versions_that_are_not_ready(documents: DocumentService) -> None:
    doc_id = _upload(documents)
    version = documents.get_document(doc_id).versions[0]

    with pytest.raises(AppError) as info:
        documents.activate_version(doc_id, version.id)

    assert info.value.code is ErrorCode.VERSION_NOT_READY


def test_retry_requeues_only_failed_versions(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents, "# عنوان فقط\n".encode())
    worker.run_until_idle()
    version = documents.get_document(doc_id).versions[0]
    assert version.status is VersionStatus.FAILED

    retried = documents.retry_version(doc_id, version.id)

    assert retried.status is VersionStatus.UPLOADED and retried.error_code is None
    assert worker.run_until_idle() == 1  # processed again (and fails again: same content)
    assert documents.get_document(doc_id).versions[0].error_code == ErrorCode.EMPTY_FILE.value


def test_retry_refuses_ready_version(documents: DocumentService, worker: IngestionWorker) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()

    with pytest.raises(AppError) as info:
        documents.retry_version(doc_id, documents.get_document(doc_id).versions[0].id)

    assert info.value.code is ErrorCode.VERSION_NOT_FAILED


# ------------------------------------------------------------------ deletion
def test_delete_document_removes_rows_then_files(
    documents: DocumentService, worker: IngestionWorker, db: Database, files: FileStore
) -> None:
    doc_id = _upload(documents)
    documents.upload_version(doc_id, "v2.md", io.BytesIO(GUIDE_V2))
    worker.run_until_idle()

    documents.delete_document(doc_id)

    for table in ("documents", "document_versions", "chunks", "ingestion_jobs"):
        assert _count(db, table) == 0, table
    assert list(files.root.iterdir()) == []
    with pytest.raises(AppError) as info:
        documents.get_document(doc_id)
    assert info.value.code is ErrorCode.NOT_FOUND


def test_active_version_cannot_be_deleted_alone(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()

    with pytest.raises(AppError) as info:
        documents.delete_version(doc_id, documents.get_document(doc_id).versions[0].id)

    assert info.value.code is ErrorCode.VERSION_IS_ACTIVE


def test_deleting_inactive_version_keeps_numbers_unique(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()
    v2 = documents.upload_version(doc_id, "bad.md", io.BytesIO("# فقط\n".encode()))
    worker.run_until_idle()

    assert documents.delete_version(doc_id, v2.id) is False
    v3 = documents.upload_version(doc_id, "v3.md", io.BytesIO(GUIDE_V2))

    assert v3.version_number == 3  # never reuses 2


def test_deleting_the_only_version_deletes_the_document(documents: DocumentService) -> None:
    doc_id = _upload(documents)

    assert documents.delete_version(doc_id, documents.get_document(doc_id).versions[0].id)
    assert documents.list_documents() == []


def test_delete_while_processing_cancels_and_writes_nothing(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    doc_id = _upload(documents)
    original = worker._repo.set_stage

    def set_stage(version_id: str, stage: ProcessingStage) -> bool:
        if stage is ProcessingStage.CHUNKING:
            documents.delete_document(doc_id)  # the user deletes mid-processing (DD-02)
        return original(version_id, stage)

    worker._repo.set_stage = set_stage  # type: ignore[method-assign]

    assert worker.run_until_idle() == 1
    for table in ("documents", "document_versions", "chunks", "ingestion_jobs"):
        assert _count(db, table) == 0, table


def test_delete_after_processing_but_before_commit_discards_results(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    doc_id = _upload(documents)
    repo = worker._repo
    original = repo.complete_ingestion

    def complete(*args: object, **kwargs: object) -> bool:
        documents.delete_document(doc_id)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    repo.complete_ingestion = complete  # type: ignore[method-assign]

    worker.run_until_idle()

    assert _count(db, "chunks") == 0


# ------------------------------------------------------------------ recovery and sweep
def test_recovery_requeues_interrupted_jobs_then_fails_after_max_attempts(
    documents: DocumentService, worker: IngestionWorker, settings: Settings
) -> None:
    doc_id = _upload(documents)
    repo = worker._repo

    for _ in range(settings.ingestion.max_attempts - 1):
        assert repo.claim_next_job() is not None  # the app "crashes" while processing
        report = worker.recover()
        assert (report.requeued, report.failed) == (1, 0)
        assert documents.get_document(doc_id).versions[0].status is VersionStatus.UPLOADED

    assert repo.claim_next_job() is not None
    report = worker.recover()

    assert (report.requeued, report.failed) == (0, 1)
    version = documents.get_document(doc_id).versions[0]
    assert version.status is VersionStatus.FAILED
    assert version.error_code == ErrorCode.INTERRUPTED.value


def test_sweep_removes_files_without_versions(documents: DocumentService, files: FileStore) -> None:
    _upload(documents)
    (files.root / "orphan.pdf").write_bytes(b"%PDF-")

    assert documents.sweep_orphan_files() == ["orphan.pdf"]
    assert len(list(files.root.iterdir())) == 1


def test_list_documents_summarises_newest_version(
    documents: DocumentService, worker: IngestionWorker
) -> None:
    a = _upload(documents, GUIDE, "أ.md")
    worker.run_until_idle()
    documents.upload_version(a, "أ2.md", io.BytesIO(GUIDE_V2))
    _upload(documents, "# ب\n\nنص.\n".encode(), "ب.md")

    rows = {r.display_name: r for r in documents.list_documents()}

    assert rows["أ"].versions == 2 and rows["أ"].latest_version == 2
    assert rows["أ"].active_version == 1 and rows["أ"].status is VersionStatus.UPLOADED
    assert rows["ب"].active_version is None
