"""Stage 5 inside the worker: vectors stored in the one commit, failures leave nothing."""

from __future__ import annotations

import io
from collections.abc import Sequence

import numpy as np
import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.config.settings import Settings
from rag_app.core.errors import ErrorCode
from rag_app.domain.models import EmbeddingTask, ProcessingStage, VersionStatus
from rag_app.ingestion.embedding import embedding_text
from rag_app.providers.ports import ProviderAuthError, ProviderRateLimitedError
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore

pytestmark = pytest.mark.integration

GUIDE = "# دليل المواعيد\n\n## إنشاء موعد\n\nيُنشأ الموعد من شاشة التقويم.\n".encode()
TWO_SECTIONS = GUIDE + "\n## إلغاء موعد\n\nيُلغى الموعد من بطاقة الموعد.\n".encode()


def _rows(db: Database, sql: str) -> list[tuple[object, ...]]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(sql)]


def _count(db: Database, table: str) -> int:
    return int(_rows(db, f"SELECT COUNT(*) FROM {table}")[0][0])  # noqa: S608


def _meta(db: Database) -> dict[str, str]:
    return {str(k): str(v) for k, v in _rows(db, "SELECT key, value FROM meta")}


def _upload(documents: DocumentService, data: bytes = GUIDE, name: str = "دليل.md") -> str:
    return documents.upload_document(name, io.BytesIO(data)).id


def _with(settings: Settings, **ingestion: object) -> Settings:
    return settings.model_copy(
        update={"ingestion": settings.ingestion.model_copy(update=ingestion)}
    )


def _worker(
    settings: Settings, db: Database, files: FileStore, provider: object
) -> IngestionWorker:
    return IngestionWorker(settings, db, files, provider)  # type: ignore[arg-type]


def test_ready_version_has_one_unit_vector_per_chunk_tagged_with_model(
    documents: DocumentService,
    worker: IngestionWorker,
    db: Database,
    embedder: FakeEmbeddingProvider,
) -> None:
    doc_id = _upload(documents, TWO_SECTIONS)

    worker.run_until_idle()

    version = documents.get_document(doc_id).active
    assert version is not None and version.status is VersionStatus.READY
    assert version.embedding_model == "fake-embedding"
    rows = _rows(
        db,
        "SELECT c.heading_path, c.text_normalized, e.model, e.dim, e.vector FROM chunks c"
        " JOIN chunk_embeddings e ON e.chunk_id = c.id ORDER BY c.seq",
    )
    assert len(rows) == version.chunk_count == 2
    for heading, text, model, dim, blob in rows:
        assert (model, dim) == ("fake-embedding", 32)
        vector = np.frombuffer(blob, dtype="<f4")  # type: ignore[arg-type]
        assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-6)
        expected = np.asarray(embedder.vector(embedding_text(str(heading), str(text))))
        assert np.allclose(vector, expected / np.linalg.norm(expected), atol=1e-6)
    assert _rows(db, "SELECT embedding_dim FROM document_versions") == [(32,)]
    assert _meta(db)["index_embedding_model"] == "fake-embedding"
    assert _meta(db)["index_embedding_dim"] == "32"
    assert {task for _, task in embedder.calls} == {EmbeddingTask.DOCUMENT}
    assert _count(db, "active_chunk_vectors") == 2


def test_chunks_are_embedded_in_configured_batches_with_progress(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider()
    embedding = settings.providers.embedding.model_copy(update={"batch_size": 1})
    small = settings.model_copy(
        update={"providers": settings.providers.model_copy(update={"embedding": embedding})}
    )
    stages: list[str] = []
    original = provider.embed

    def spy(texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        stages.append(_rows(db, "SELECT stage FROM document_versions")[0][0])  # type: ignore[arg-type]
        return original(texts, task)

    provider.embed = spy  # type: ignore[method-assign]
    _upload(documents, TWO_SECTIONS)

    _worker(small, db, files, provider).run_until_idle()

    assert [len(texts) for texts, _ in provider.calls] == [1, 1]
    assert stages == [ProcessingStage.EMBEDDING.value] * 2


def test_permanent_provider_failure_fails_version_and_stores_nothing(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider(failures=[ProviderAuthError("HTTP 401")])
    doc_id = _upload(documents)

    _worker(settings, db, files, provider).run_until_idle()

    (version,) = documents.get_document(doc_id).versions
    assert version.status is VersionStatus.FAILED
    assert version.error_code == ErrorCode.PROVIDER_AUTH.value
    assert version.error_message == "مفتاح مزود النموذج غير صالح. راجع الإعدادات."
    assert _count(db, "chunks") == _count(db, "chunk_embeddings") == 0
    assert len(provider.calls) == 1  # not retried


def test_transient_failures_are_retried_until_ready(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider(
        failures=[ProviderRateLimitedError("HTTP 429"), ProviderRateLimitedError("HTTP 429")]
    )
    doc_id = _upload(documents)

    _worker(_with(settings, provider_retry_initial_seconds=0), db, files, provider).run_until_idle()

    assert documents.get_document(doc_id).active is not None
    assert len(provider.calls) == 3


def test_exhausted_retries_fail_the_version_and_user_retry_recovers(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    fast = _with(settings, provider_retry_initial_seconds=0, provider_retry_attempts=2)
    provider = FakeEmbeddingProvider(failures=[ProviderRateLimitedError("429")] * 2)
    doc_id = _upload(documents)
    worker = _worker(fast, db, files, provider)

    worker.run_until_idle()
    (failed,) = documents.get_document(doc_id).versions
    assert failed.error_code == ErrorCode.PROVIDER_RATE_LIMITED.value
    documents.retry_version(doc_id, failed.id)
    worker.run_until_idle()

    assert documents.get_document(doc_id).active is not None
    assert _count(db, "chunk_embeddings") == 1


def test_failed_new_version_keeps_previous_version_and_its_vectors_active(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider()
    worker = _worker(settings, db, files, provider)
    doc_id = _upload(documents)
    worker.run_until_idle()
    provider.failures.append(ProviderAuthError("401"))

    documents.upload_version(doc_id, "دليل.md", io.BytesIO(TWO_SECTIONS))
    worker.run_until_idle()

    detail = documents.get_document(doc_id)
    assert detail.active is not None and detail.active.version_number == 1
    assert detail.versions[0].status is VersionStatus.FAILED
    assert _count(db, "active_chunk_vectors") == 1


def test_delete_during_embedding_cancels_and_leaves_no_rows(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider()
    embedding = settings.providers.embedding.model_copy(update={"batch_size": 1})
    small = settings.model_copy(
        update={"providers": settings.providers.model_copy(update={"embedding": embedding})}
    )
    doc_id = _upload(documents, TWO_SECTIONS)
    original = provider.embed

    def delete_then_embed(texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        if not provider.calls:
            documents.delete_document(doc_id)
        return original(texts, task)

    provider.embed = delete_then_embed  # type: ignore[method-assign]

    _worker(small, db, files, provider).run_until_idle()

    assert len(provider.calls) == 1  # stopped before the second batch
    for table in ("documents", "document_versions", "chunks", "chunk_embeddings"):
        assert _count(db, table) == 0, table


def test_new_model_is_refused_while_the_index_holds_another_model(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    first = _upload(documents)
    _worker(settings, db, files, FakeEmbeddingProvider(model="model-a")).run_until_idle()
    other = FakeEmbeddingProvider(model="model-b")
    second = _upload(documents, b"# other\n\ntext\n", "b.md")

    _worker(settings, db, files, other).run_until_idle()

    (version,) = documents.get_document(second).versions
    assert version.status is VersionStatus.FAILED
    assert version.error_code == ErrorCode.REINDEX_REQUIRED.value
    assert other.calls == []  # refused before spending quota
    assert documents.get_document(first).active is not None
    assert {r[0] for r in _rows(db, "SELECT model FROM chunk_embeddings")} == {"model-a"}


def test_an_empty_index_adopts_the_new_model(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    doc_id = _upload(documents)
    _worker(settings, db, files, FakeEmbeddingProvider(model="model-a")).run_until_idle()
    documents.delete_document(doc_id)

    _upload(documents)
    _worker(settings, db, files, FakeEmbeddingProvider(model="model-b", dim=8)).run_until_idle()

    assert _meta(db)["index_embedding_model"] == "model-b"
    assert _meta(db)["index_embedding_dim"] == "8"


def test_deleting_documents_and_versions_removes_their_vectors(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    doc_id = _upload(documents)
    worker.run_until_idle()
    version_one = documents.get_document(doc_id).versions[0].id
    documents.upload_version(doc_id, "دليل.md", io.BytesIO(TWO_SECTIONS))
    worker.run_until_idle()
    assert _count(db, "chunk_embeddings") == 3

    documents.delete_version(doc_id, version_one)
    assert _count(db, "chunk_embeddings") == 2
    documents.delete_document(doc_id)

    assert _count(db, "chunks") == _count(db, "chunk_embeddings") == 0


def test_shutdown_during_a_provider_wait_leaves_the_job_for_recovery(
    settings: Settings, documents: DocumentService, db: Database, files: FileStore
) -> None:
    provider = FakeEmbeddingProvider(failures=[ProviderRateLimitedError("429")])
    patient = _with(settings, provider_retry_initial_seconds=300)
    worker = _worker(patient, db, files, provider)
    doc_id = _upload(documents)
    worker._stop.set()  # the app is stopping: the 300 s backoff must not block it

    assert worker.run_once() is True

    (version,) = documents.get_document(doc_id).versions
    assert version.status is VersionStatus.PROCESSING
    assert _count(db, "chunks") == 0
    assert worker.recover().requeued == 1
    worker._stop.clear()
    worker.run_until_idle()
    assert documents.get_document(doc_id).active is not None
