"""Re-indexing: all ready versions move to the configured model in one swap, or not at all."""

from __future__ import annotations

import io
from collections.abc import Sequence

import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.config.settings import Settings
from rag_app.domain.models import EmbeddingTask
from rag_app.providers.ports import ProviderAuthError
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.services.reindex import ReindexService
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.repositories.index import IndexRepository

pytestmark = pytest.mark.integration

GUIDE = "# دليل\n\n## أ\n\nنص أول.\n\n## ب\n\nنص ثان.\n".encode()
GUIDE_V2 = GUIDE + "\n## ج\n\nنص ثالث.\n".encode()
OTHER = "# سياسة\n\nنص السياسة.\n".encode()


def _rows(db: Database, sql: str) -> list[tuple[object, ...]]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(sql)]


def _models(db: Database) -> dict[str, int]:
    rows = _rows(db, "SELECT model, COUNT(*) FROM chunk_embeddings GROUP BY model")
    return {str(m): int(n) for m, n in rows}  # type: ignore[call-overload]


def _meta(db: Database) -> dict[str, str]:
    return {str(k): str(v) for k, v in _rows(db, "SELECT key, value FROM meta")}


@pytest.fixture
def library(
    settings: Settings, db: Database, files: FileStore, documents: DocumentService
) -> dict[str, str]:
    """Two documents indexed with model-a; the guide has an inactive older version (DD-01)."""
    worker = IngestionWorker(settings, db, files, FakeEmbeddingProvider(model="model-a"))
    guide = documents.upload_document("دليل.md", io.BytesIO(GUIDE)).id
    worker.run_until_idle()
    documents.upload_version(guide, "دليل.md", io.BytesIO(GUIDE_V2))
    other = documents.upload_document("سياسة.md", io.BytesIO(OTHER)).id
    worker.run_until_idle()
    assert _models(db) == {"model-a": 6}  # 2 (v1, inactive) + 3 (v2) + 1
    return {"guide": guide, "other": other}


def _service(db: Database, provider: object, batch_size: int = 2) -> ReindexService:
    return ReindexService(db, provider, batch_size=batch_size)  # type: ignore[arg-type]


def test_model_change_reembeds_every_ready_version_including_inactive_ones(
    db: Database, library: dict[str, str]
) -> None:
    provider = FakeEmbeddingProvider(model="model-b", dim=16)
    generation = int(_meta(db)["index_generation"])
    progress: list[tuple[int, int]] = []

    report = _service(db, provider).run(on_progress=lambda d, t: progress.append((d, t)))

    assert report.completed and report.embedded == report.vectors == 6
    assert (report.model, report.dim) == ("model-b", 16)
    assert _models(db) == {"model-b": 6}
    assert _meta(db)["index_embedding_model"] == "model-b"
    assert _meta(db)["index_embedding_dim"] == "16"
    assert int(_meta(db)["index_generation"]) == generation + 1
    assert set(_rows(db, "SELECT embedding_model, embedding_dim FROM document_versions")) == {
        ("model-b", 16)
    }
    assert progress == [(0, 6), (2, 6), (4, 6), (6, 6)]
    assert {task for _, task in provider.calls} == {EmbeddingTask.DOCUMENT}
    assert IndexRepository(db).consistency().problems == 0


def test_versions_ready_before_embeddings_existed_get_vectors(
    db: Database, library: dict[str, str]
) -> None:
    with db.transaction() as conn:  # the state Phase 6 left behind (D-034)
        conn.execute("DELETE FROM chunk_embeddings")
        conn.execute("UPDATE document_versions SET embedding_model = NULL, embedding_dim = NULL")
        conn.execute("UPDATE meta SET value = '' WHERE key = 'index_embedding_model'")
    assert IndexRepository(db).consistency().versions_missing_vectors == 3
    service = _service(db, FakeEmbeddingProvider(model="model-a"))
    assert service.plan().chunks_to_embed == 6

    report = service.run()

    assert report.completed
    assert _models(db) == {"model-a": 6}
    assert IndexRepository(db).consistency().versions_missing_vectors == 0
    assert len(_rows(db, "SELECT * FROM active_chunk_vectors")) == 4


def test_up_to_date_index_needs_no_provider_call(db: Database, library: dict[str, str]) -> None:
    provider = FakeEmbeddingProvider(model="model-a")

    plan = _service(db, provider).plan()

    assert plan.up_to_date and plan.chunks_to_embed == 0
    assert provider.calls == []


def test_failure_leaves_live_index_intact_and_rerun_resumes_from_staging(
    db: Database, library: dict[str, str]
) -> None:
    failing = FakeEmbeddingProvider(model="model-b", failures=[None, ProviderAuthError("401")])

    with pytest.raises(ProviderAuthError):
        _service(db, failing).run()

    assert _models(db) == {"model-a": 6}
    assert _meta(db)["index_embedding_model"] == "model-a"
    assert IndexRepository(db).consistency().staged_vectors == 2
    resumed = FakeEmbeddingProvider(model="model-b")
    plan = _service(db, resumed).plan()
    assert (plan.chunks_to_embed, plan.staged_reusable) == (4, 2)

    report = _service(db, resumed).run()

    assert report.completed and report.embedded == 4  # the 2 staged vectors were reused
    assert resumed.texts_embedded == 4
    assert _models(db) == {"model-b": 6}
    assert IndexRepository(db).consistency().staged_vectors == 0


def test_staged_vectors_of_an_abandoned_model_are_discarded(
    db: Database, library: dict[str, str]
) -> None:
    abandoned = FakeEmbeddingProvider(model="model-b", failures=[None, ProviderAuthError("401")])
    with pytest.raises(ProviderAuthError):
        _service(db, abandoned).run()

    report = _service(db, FakeEmbeddingProvider(model="model-c")).run()

    assert report.embedded == 6
    assert _models(db) == {"model-c": 6}


def test_versions_finishing_during_reindex_are_picked_up_by_another_pass(
    settings: Settings,
    db: Database,
    files: FileStore,
    documents: DocumentService,
    library: dict[str, str],
) -> None:
    old_worker = IngestionWorker(settings, db, files, FakeEmbeddingProvider(model="model-a"))
    provider = FakeEmbeddingProvider(model="model-b")
    original = provider.embed

    def ingest_meanwhile(texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        if not provider.calls:  # an app still running with the old model finishes a version
            documents.upload_document("late.md", io.BytesIO(b"# late\n\ntext\n"))
            old_worker.run_until_idle()
        return original(texts, task)

    provider.embed = ingest_meanwhile  # type: ignore[method-assign]

    report = _service(db, provider).run()

    assert report.completed and report.vectors == 7
    assert _models(db) == {"model-b": 7}


def test_gives_up_without_touching_the_index_when_versions_keep_arriving(
    settings: Settings,
    db: Database,
    files: FileStore,
    documents: DocumentService,
    library: dict[str, str],
) -> None:
    old_worker = IngestionWorker(settings, db, files, FakeEmbeddingProvider(model="model-a"))
    provider = FakeEmbeddingProvider(model="model-b")
    original = provider.embed

    def ingest_every_time(texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        n = len(provider.calls)
        documents.upload_document(f"late{n}.md", io.BytesIO(f"# late {n}\n\ntext {n}\n".encode()))
        old_worker.run_until_idle()
        return original(texts, task)

    provider.embed = ingest_every_time  # type: ignore[method-assign]
    service = ReindexService(db, provider, batch_size=100, max_passes=2)  # type: ignore[arg-type]

    report = service.run()

    assert not report.completed
    assert set(_models(db)) == {"model-a"}  # live index untouched
    assert _meta(db)["index_embedding_model"] == "model-a"


def test_chunks_deleted_while_their_batch_is_embedded_are_skipped(
    db: Database, documents: DocumentService, library: dict[str, str]
) -> None:
    provider = FakeEmbeddingProvider(model="model-b")
    original = provider.embed

    def delete_meanwhile(texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        if not provider.calls:
            documents.delete_document(library["other"])
        return original(texts, task)

    provider.embed = delete_meanwhile  # type: ignore[method-assign]

    report = _service(db, provider, batch_size=10).run()

    assert report.completed and report.vectors == 5
    assert _models(db) == {"model-b": 5}
