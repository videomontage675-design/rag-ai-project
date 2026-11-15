import io
from pathlib import Path

import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.config.settings import Settings
from rag_app.services.diagnostics import CheckLevel, run_checks
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.migrate import apply_migrations

pytestmark = pytest.mark.unit


def _by_name(settings: Settings) -> dict[str, CheckLevel]:
    return {r.name: r.level for r in run_checks(settings)}


def test_missing_required_keys_fail_and_judge_key_only_warns(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "COHERE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    levels = _by_name(settings)

    assert levels["API key: embedding"] is CheckLevel.FAIL
    assert levels["API key: chat"] is CheckLevel.FAIL
    assert levels["API key: judge (evaluation only)"] is CheckLevel.WARN


def test_present_keys_pass(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "x")

    levels = _by_name(settings)

    assert levels["API key: embedding"] is CheckLevel.OK
    assert levels["API key: chat"] is CheckLevel.OK


def test_poppler_missing_in_configured_folder_fails(settings: Settings, tmp_path: Path) -> None:
    empty = tmp_path / "no-poppler"
    empty.mkdir()
    patched = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"poppler_bin_dir": empty})}
    )

    assert _by_name(patched)["poppler (pdftotext)"] is CheckLevel.FAIL


def test_database_check_creates_schema(settings: Settings) -> None:
    assert _by_name(settings)["database"] is CheckLevel.OK
    assert settings.database_file.exists()


def _index_check(settings: Settings) -> tuple[CheckLevel, str]:
    (result,) = [r for r in run_checks(settings) if r.name == "vector index"]
    return result.level, result.detail


def _prepare(settings: Settings, model: str, *, drop_vectors: bool = False) -> None:
    db = Database(settings.database_file)
    apply_migrations(db)
    files = FileStore(settings.uploads_dir)
    DocumentService(settings, db, files).upload_document("a.md", io.BytesIO(b"# a\n\ntext\n"))
    IngestionWorker(settings, db, files, FakeEmbeddingProvider(model=model)).run_until_idle()
    if drop_vectors:
        with db.transaction() as conn:
            conn.execute("DELETE FROM chunk_embeddings")


def test_index_check_passes_on_empty_and_current_index(settings: Settings) -> None:
    assert _index_check(settings) == (CheckLevel.OK, "0 ready versions (empty)")

    _prepare(settings, settings.providers.embedding.model)

    level, detail = _index_check(settings)
    assert level is CheckLevel.OK and "1 ready versions" in detail


def test_index_check_warns_when_reindex_is_needed(settings: Settings) -> None:
    _prepare(settings, "old-model")

    level, detail = _index_check(settings)

    assert level is CheckLevel.WARN
    assert "old-model" in detail and "rag reindex" in detail


def test_index_check_warns_about_versions_without_vectors(settings: Settings) -> None:
    _prepare(settings, settings.providers.embedding.model, drop_vectors=True)

    level, detail = _index_check(settings)

    assert level is CheckLevel.WARN
    assert detail.startswith("1 ready versions have no vectors")


def test_index_check_fails_on_mixed_models(settings: Settings) -> None:
    _prepare(settings, settings.providers.embedding.model)
    db = Database(settings.database_file)
    with db.transaction() as conn:
        conn.execute("UPDATE chunk_embeddings SET model = 'intruder'")

    level, detail = _index_check(settings)

    assert level is CheckLevel.FAIL and "1 vectors of other models" in detail
