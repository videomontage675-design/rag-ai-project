"""Phase 7 acceptance: vectors in the one commit, identity per vector, no orphans.

Requirements: FR-ING-11, FR-ING-12, FR-ING-13.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from rag_app.core.errors import ErrorCode
from rag_app.domain.models import VersionStatus
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from support.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration

GUIDE = (
    "# دليل\n\n## المواعيد\n\nيُنشأ الموعد من التقويم.\n\n## الفوترة\n\nتصدر الفاتورة بعد الزيارة.\n"
).encode()


def _rows(db: Database, sql: str, *params: str) -> list[tuple]:
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(sql, params)]


def test_every_chunk_gets_a_normalized_vector_tagged_with_model_and_dim(
    documents: DocumentService, worker: IngestionWorker, db: Database, fake_embedder: FakeEmbedder
) -> None:
    doc_id = documents.upload_document("دليل.md", io.BytesIO(GUIDE)).id

    worker.run_until_idle()

    rows = _rows(
        db,
        "SELECT c.heading_path, e.model, e.dim, e.vector FROM chunks c "
        "JOIN chunk_embeddings e ON e.chunk_id = c.id ORDER BY c.seq",
    )
    assert len(rows) == 2
    for _, model, dim, blob in rows:
        assert (model, dim) == ("fake-embedding", 32)
        vector = np.frombuffer(blob, dtype="<f4")
        assert vector.shape == (32,) and abs(float(np.linalg.norm(vector)) - 1.0) < 1e-5
    # The embedded text carries the heading path (stage 5 rule): one call, document task.
    assert fake_embedder.calls == [(2, "document")]
    version = documents.get_document(doc_id).versions[0]
    assert _rows(
        db,
        "SELECT embedding_model, embedding_dim FROM document_versions WHERE id = ?",
        version.id,
    ) == [("fake-embedding", 32)]
    meta = dict(_rows(db, "SELECT key, value FROM meta"))
    assert meta["index_embedding_model"] == "fake-embedding" and meta["index_embedding_dim"] == "32"
    assert len(_rows(db, "SELECT chunk_id FROM active_chunk_vectors")) == 2  # searchable now


def test_provider_failure_fails_the_version_and_writes_nothing(
    documents: DocumentService, worker: IngestionWorker, db: Database, fake_embedder: FakeEmbedder
) -> None:
    doc_id = documents.upload_document("دليل.md", io.BytesIO(GUIDE)).id
    worker.run_until_idle()
    fake_embedder.fail_with = ErrorCode.PROVIDER_RATE_LIMITED

    documents.upload_version(doc_id, "v2.md", io.BytesIO(GUIDE + "\n## جديد\n\nنص.\n".encode()))
    worker.run_until_idle()

    detail = documents.get_document(doc_id)
    new, old = detail.versions
    assert new.status is VersionStatus.FAILED
    assert new.error_code == ErrorCode.PROVIDER_RATE_LIMITED.value
    assert "حد الاستخدام" in (new.error_message or "")
    assert detail.active_version_id == old.id  # the previous version keeps answering
    assert _rows(db, "SELECT COUNT(*) FROM chunks WHERE version_id = ?", new.id) == [(0,)]
    assert len(_rows(db, "SELECT chunk_id FROM active_chunk_vectors")) == 2


def test_deleting_a_document_removes_its_vectors(
    documents: DocumentService, worker: IngestionWorker, db: Database
) -> None:
    doc_id = documents.upload_document("دليل.md", io.BytesIO(GUIDE)).id
    worker.run_until_idle()

    documents.delete_document(doc_id)

    assert _rows(db, "SELECT COUNT(*) FROM chunk_embeddings") == [(0,)]


def test_first_index_identity_is_kept_when_configuration_changes(
    documents: DocumentService, worker: IngestionWorker, db: Database, fake_embedder: FakeEmbedder
) -> None:
    documents.upload_document("a.md", io.BytesIO(GUIDE))
    worker.run_until_idle()
    fake_embedder._model = "another-model"

    documents.upload_document("b.md", io.BytesIO(GUIDE + b"\n"))
    worker.run_until_idle()

    meta = dict(_rows(db, "SELECT key, value FROM meta"))
    assert meta["index_embedding_model"] == "fake-embedding"  # only re-indexing changes it
