"""VectorIndex: only active, ready vectors; reloaded exactly when the generation changes."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.core.errors import AppError, ErrorCode
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.vector_index import VectorIndex

pytestmark = pytest.mark.integration

GUIDE = "# دليل\n\n## أ\n\nنص أول.\n".encode()
GUIDE_V2 = GUIDE + "\n## ب\n\nنص ثان.\n".encode()


def _upload(documents: DocumentService, data: bytes, name: str = "دليل.md") -> str:
    return documents.upload_document(name, io.BytesIO(data)).id


def _active_chunk_ids(db: Database) -> set[str]:
    with db.connect() as conn:
        return {r[0] for r in conn.execute("SELECT chunk_id FROM active_chunk_vectors")}


def test_empty_index_has_no_rows(db: Database) -> None:
    snapshot = VectorIndex(db).current()

    assert len(snapshot) == 0
    assert snapshot.vectors.shape == (0, 0)
    assert snapshot.model == ""


def test_loads_active_vectors_with_their_chunks_and_documents(
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
    embedder: FakeEmbeddingProvider,
) -> None:
    doc_id = _upload(documents, GUIDE_V2)
    worker.run_until_idle()

    snapshot = VectorIndex(db).current()

    assert (snapshot.model, snapshot.dim) == (embedder.model, embedder.dim)
    assert set(snapshot.chunk_ids) == _active_chunk_ids(db)
    assert snapshot.document_ids == (doc_id, doc_id)
    assert snapshot.vectors.shape == (2, embedder.dim)
    assert snapshot.vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(snapshot.vectors, axis=1), 1.0, atol=1e-6)
    with pytest.raises(ValueError, match="read-only"):
        snapshot.vectors[0, 0] = 1.0


def test_unchanged_generation_reuses_the_loaded_snapshot(
    db: Database, documents: DocumentService, worker: IngestionWorker
) -> None:
    _upload(documents, GUIDE)
    worker.run_until_idle()
    index = VectorIndex(db)

    assert index.current() is index.current()


def test_version_changes_reload_and_only_the_active_version_is_searchable(
    db: Database, documents: DocumentService, worker: IngestionWorker
) -> None:
    doc_id = _upload(documents, GUIDE)
    worker.run_until_idle()
    index = VectorIndex(db)
    first = index.current()
    v1 = documents.get_document(doc_id).versions[0].id

    documents.upload_version(doc_id, "دليل.md", io.BytesIO(GUIDE_V2))
    assert index.current() is first  # still processing: nothing changed for search
    worker.run_until_idle()
    second = index.current()
    documents.activate_version(doc_id, v1)
    third = index.current()

    assert len(first) == 1 and len(second) == 2 and len(third) == 1
    assert third.chunk_ids == first.chunk_ids
    assert first.generation < second.generation < third.generation


def test_deleted_and_failed_documents_are_not_loaded(
    db: Database,
    documents: DocumentService,
    worker: IngestionWorker,
    embedder: FakeEmbeddingProvider,
) -> None:
    keep = _upload(documents, GUIDE, "keep.md")
    gone = _upload(documents, GUIDE_V2, "gone.md")
    worker.run_until_idle()
    index = VectorIndex(db)
    assert len(index.current()) == 3

    documents.delete_document(gone)
    embedder.failures.append(AppError(ErrorCode.PROVIDER_AUTH))
    _upload(documents, b"# failed\n\ntext\n", "failed.md")
    worker.run_until_idle()

    assert set(index.current().document_ids) == {keep}


def test_vectors_disagreeing_with_the_index_model_are_refused(
    db: Database, documents: DocumentService, worker: IngestionWorker
) -> None:
    _upload(documents, GUIDE)
    worker.run_until_idle()
    with db.transaction() as conn:  # simulate a hand-edited database
        conn.execute("UPDATE chunk_embeddings SET model = 'other'")
        conn.execute(
            "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
            " WHERE key = 'index_generation'"
        )

    with pytest.raises(AppError) as info:
        VectorIndex(db).current()

    assert info.value.code is ErrorCode.REINDEX_REQUIRED


def test_concurrent_readers_share_one_consistent_snapshot(
    db: Database, documents: DocumentService, worker: IngestionWorker
) -> None:
    _upload(documents, GUIDE_V2)
    worker.run_until_idle()
    index = VectorIndex(db)

    with ThreadPoolExecutor(max_workers=8) as pool:
        snapshots = list(pool.map(lambda _: index.current(), range(32)))

    assert len({id(s) for s in snapshots}) == 1
