"""The whole ingestion path as the app wires it, with only the provider's HTTP mocked.

Upload → worker → real OpenAI-compatible adapter (respx in place of Gemini) → retries →
one commit → VectorIndex. Then the full sample corpus (D02 replaced by its v2, as in the
golden set's default state) through the same path.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient

from rag_app.config.settings import Settings
from rag_app.services.documents import DocumentService
from rag_app.storage.repositories.index import IndexRepository
from rag_app.storage.vector_index import VectorIndex
from rag_app.web.app import create_app
from rag_app.web.context import AppContext

pytestmark = pytest.mark.integration

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
CORPUS = Path(__file__).resolve().parents[3] / "data" / "sample_corpus"
DIM = 8


def _vectors(request: httpx.Request) -> httpx.Response:
    """A Gemini-shaped response (no ``index``), one deterministic vector per input."""
    texts = json.loads(request.content)["input"]
    data = [
        {"embedding": [float(len(t) % 7 + 1)] + [float(i + 1)] * (DIM - 1)}
        for i, t in enumerate(texts)
    ]
    return httpx.Response(200, json={"object": "list", "data": data})


@pytest.fixture
def app_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app exactly as configured, except that provider backoff does not wait."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    no_wait = settings.ingestion.model_copy(update={"provider_retry_initial_seconds": 0})
    app = create_app(settings.model_copy(update={"ingestion": no_wait}))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def _ctx(client: TestClient) -> AppContext:
    context: AppContext = client.app.state.context  # type: ignore[attr-defined]
    return context


@respx.mock
def test_configured_adapter_embeds_uploads_through_the_app(app_client: TestClient) -> None:
    route = respx.post(GEMINI).mock(
        side_effect=[httpx.Response(503), httpx.Response(429), _vectors]
    )
    ctx = _ctx(app_client)
    upload = app_client.post(
        "/api/v1/documents",
        files={"file": ("دليل.md", "# دليل\n\n## إنشاء موعد\n\nمن شاشة التقويم.\n".encode())},
    )
    assert upload.status_code == 202

    ctx.worker.run_until_idle()

    detail = app_client.get(f"/api/v1/documents/{upload.json()['id']}").json()
    assert detail["versions"][0]["status"] == "ready"
    assert detail["versions"][0]["embedding_model"] == "gemini-embedding-001"
    assert route.call_count == 3  # 503 and 429 were retried
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body == {
        "model": "gemini-embedding-001",
        "input": ["دليل › إنشاء موعد\nمن شاشة التقويم."],
    }
    snapshot = VectorIndex(ctx.db).current()
    assert (len(snapshot), snapshot.dim, snapshot.model) == (1, DIM, "gemini-embedding-001")


def _corpus_uploads() -> list[tuple[str, str, Path]]:
    manifest = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
    uploads = []
    for document in manifest["documents"]:
        for version in document["versions"]:
            uploads.append((document["id"], version["version"], CORPUS / version["upload_file"]))
    return uploads


@respx.mock
def test_whole_sample_corpus_is_embedded_consistently(app_client: TestClient) -> None:
    respx.post(GEMINI).mock(side_effect=_vectors)
    ctx = _ctx(app_client)
    service: DocumentService = ctx.documents
    ids: dict[str, str] = {}

    for doc, _version, path in _corpus_uploads():
        data = io.BytesIO(path.read_bytes())
        if doc in ids:
            service.upload_version(ids[doc], path.name, data)
        else:
            ids[doc] = service.upload_document(path.name, data).id
        ctx.worker.run_until_idle()

    details = [service.get_document(i) for i in ids.values()]
    assert all(v.status.value == "ready" for d in details for v in d.versions)
    state = IndexRepository(ctx.db).consistency()
    assert (state.problems, state.versions_missing_vectors) == (0, 0)
    assert state.ready_versions == len(_corpus_uploads())
    active_chunks = sum(d.active.chunk_count or 0 for d in details if d.active)
    snapshot = VectorIndex(ctx.db).current()
    assert len(snapshot) == active_chunks
    assert set(snapshot.document_ids) == set(ids.values())
