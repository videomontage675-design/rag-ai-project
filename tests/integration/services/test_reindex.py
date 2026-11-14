"""Re-indexing (FR-CFG-05, FR-RET-03, DESIGN-001 §7.4) and the index state shown to users."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from rag_app.cli import main
from rag_app.config.settings import Settings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.services.documents import DocumentService
from rag_app.services.indexing import IndexingService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.services.system import get_system_status
from rag_app.storage.db import Database
from support.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration

GUIDE = "# دليل\n\n## المواعيد\n\nيُنشأ الموعد من التقويم.\n".encode()


def _scalar(db: Database, sql: str) -> object:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()[0]


def _two_versions(documents: DocumentService, worker: IngestionWorker) -> str:
    doc_id = documents.upload_document("دليل.md", io.BytesIO(GUIDE)).id
    documents.upload_version(doc_id, "v2.md", io.BytesIO(GUIDE + "\n## إلغاء\n\nنص.\n".encode()))
    worker.run_until_idle()
    return doc_id


def _strip_vectors(db: Database) -> None:
    """Make the data look like Phase 6: chunks and ready versions, but no vectors."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM chunk_embeddings")
        conn.execute("UPDATE document_versions SET embedding_model = NULL, embedding_dim = NULL")
        conn.execute("UPDATE meta SET value = '' WHERE key = 'index_embedding_model'")
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'index_embedding_dim'")


def _service(settings: Settings, db: Database, fake: FakeEmbedder) -> IndexingService:
    config = settings.providers.embedding.model_copy(update={"model": fake.model, "dimensions": 32})
    providers = settings.providers.model_copy(update={"embedding": config})
    return IndexingService(settings.model_copy(update={"providers": providers}), db, lambda: fake)


def test_versions_without_vectors_are_counted_and_embedded(
    settings: Settings,
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
    fake_embedder: FakeEmbedder,
) -> None:
    _two_versions(documents, worker)
    _strip_vectors(db)
    service = _service(settings, db, fake_embedder)
    assert service.pending_versions() == 2  # the inactive version too (DD-01)
    generation = int(str(_scalar(db, "SELECT value FROM meta WHERE key='index_generation'")))
    progress: list[tuple[int, int]] = []

    report = service.reindex(lambda done, total: progress.append((done, total)))

    assert (report.versions, report.chunks) == (2, 3)
    assert progress == [(1, 2), (2, 2)]
    assert service.pending_versions() == 0
    assert _scalar(db, "SELECT COUNT(*) FROM chunk_embeddings") == 3
    assert (
        _scalar(db, "SELECT value FROM meta WHERE key='index_embedding_model'") == "fake-embedding"
    )
    assert (
        int(str(_scalar(db, "SELECT value FROM meta WHERE key='index_generation'")))
        == generation + 1
    )
    assert service.reindex().versions == 0  # idempotent


def test_model_change_requires_reindex_and_reindex_switches_everything(
    settings: Settings,
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
    fake_embedder: FakeEmbedder,
) -> None:
    _two_versions(documents, worker)
    new = FakeEmbedder(model="new-model", dimensions=16)
    service = _service(settings, db, new)

    assert service.pending_versions() == 2
    service.reindex()

    assert _scalar(db, "SELECT COUNT(DISTINCT model || dim) FROM chunk_embeddings") == 1
    assert _scalar(db, "SELECT model FROM chunk_embeddings LIMIT 1") == "new-model"
    assert _scalar(db, "SELECT value FROM meta WHERE key='index_embedding_dim'") == "16"


def test_failure_during_reindex_leaves_the_old_index_intact(
    settings: Settings,
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
) -> None:
    _two_versions(documents, worker)
    broken = FakeEmbedder(model="new-model")
    broken.fail_with = ErrorCode.PROVIDER_UNAVAILABLE

    with pytest.raises(AppError):
        _service(settings, db, broken).reindex()

    assert _scalar(db, "SELECT COUNT(*) FROM chunk_embeddings WHERE model = 'fake-embedding'") == 3
    assert (
        _scalar(db, "SELECT value FROM meta WHERE key='index_embedding_model'") == "fake-embedding"
    )


def test_version_deleted_while_reindexing_is_skipped(
    settings: Settings,
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
) -> None:
    doc_id = _two_versions(documents, worker)
    old_version = documents.get_document(doc_id).versions[1].id

    class DeletingEmbedder(FakeEmbedder):
        def embed(self, texts: list[str], task: str) -> object:  # type: ignore[override]
            if not self.calls:
                documents.delete_version(doc_id, old_version)
            return super().embed(texts, task)  # type: ignore[arg-type]

    report = _service(settings, db, DeletingEmbedder(model="new-model")).reindex()

    assert report.versions == 1
    assert _scalar(db, "SELECT COUNT(*) FROM chunk_embeddings") == 2


def test_status_reports_reindex_need_and_the_ui_shows_a_notice(
    settings: Settings, db: Database, client: TestClient
) -> None:
    client.post("/api/v1/documents", files={"file": ("a.md", GUIDE)})
    client.app.state.context.worker.run_until_idle()  # type: ignore[attr-defined]
    _strip_vectors(db)

    status = get_system_status(settings, db)
    assert status.versions_needing_index == 1 and status.reindex_required is False
    assert client.get("/api/v1/system/status").json()["versions_needing_index"] == 1
    page = client.get("/documents").text
    assert "نسخة واحدة غير مفهرسة" in page and "rag reindex" in page

    with db.transaction() as conn:
        conn.execute("UPDATE meta SET value = 'old-model' WHERE key = 'index_embedding_model'")
    assert get_system_status(settings, db).reindex_required is True
    assert "يلزم إعادة فهرسة المستندات" in client.get("/").text


def test_cli_reindex_reports_and_embeds(
    config_dir: object,
    settings: Settings,
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _two_versions(documents, worker)
    _strip_vectors(db)
    fake = FakeEmbedder(model=settings.providers.embedding.model, dimensions=768)
    monkeypatch.setattr("rag_app.cli.build_embedder", lambda *_: fake)
    args = ["--settings", str(settings.source_file), "reindex"]

    assert main(args) == 0
    assert "2 version(s), 3 chunk(s)" in capsys.readouterr().out
    assert main(args) == 0
    assert "Nothing to do" in capsys.readouterr().out

    _strip_vectors(db)
    fake.fail_with = ErrorCode.PROVIDER_AUTH
    assert main(args) == 1
    assert "PROVIDER_AUTH" in capsys.readouterr().err
