import io
from pathlib import Path

import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.cli import main
from rag_app.config.settings import load_settings
from rag_app.providers.ports import ProviderAuthError
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.migrate import apply_migrations

pytestmark = pytest.mark.integration


def test_check_exits_1_and_reports_missing_keys(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "COHERE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    code = main(["--settings", str(config_dir / "settings.toml"), "check"])

    out = capsys.readouterr().out
    assert code == 1
    assert "GEMINI_API_KEY is not set" in out
    assert "database" in out


def test_check_reads_keys_from_dotenv_next_to_config(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    (config_dir.parent / ".env").write_text("GEMINI_API_KEY=a\nGROQ_API_KEY=b\n", encoding="utf-8")

    main(["--settings", str(config_dir / "settings.toml"), "check"])

    out = capsys.readouterr().out
    assert "GEMINI_API_KEY is set" in out
    assert "GROQ_API_KEY is set" in out


def test_invalid_settings_exit_2_with_arabic_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--settings", str(tmp_path / "missing.toml"), "check"])

    err = capsys.readouterr().err
    assert code == 2
    assert "CONFIG_INVALID" in err
    assert "إعدادات" in err


# ------------------------------------------------------------------ reindex
class _ClosableFake(FakeEmbeddingProvider):
    closed = False

    def close(self) -> None:
        self.closed = True


def _reindex(config_dir: Path, monkeypatch: pytest.MonkeyPatch, provider: _ClosableFake) -> int:
    monkeypatch.setattr("rag_app.cli.open_embedding_provider", lambda cfg: provider)
    monkeypatch.setattr("rag_app.cli.configure_logging", lambda *a, **k: None)
    return main(["--settings", str(config_dir / "settings.toml"), "reindex"])


def _ingest(config_dir: Path, model: str) -> None:
    settings = load_settings(config_dir / "settings.toml")
    db = Database(settings.database_file)
    apply_migrations(db)
    files = FileStore(settings.uploads_dir)
    worker = IngestionWorker(settings, db, files, FakeEmbeddingProvider(model=model))
    DocumentService(settings, db, files).upload_document("a.md", io.BytesIO(b"# A\n\ntext\n"))
    worker.run_until_idle()


def test_reindex_on_empty_index_reports_nothing_to_do(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _ClosableFake(model="gemini-embedding-001")

    code = _reindex(config_dir, monkeypatch, provider)

    assert code == 0
    assert "up to date" in capsys.readouterr().out
    assert provider.calls == [] and provider.closed


def test_reindex_moves_the_index_to_the_configured_model(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest(config_dir, "old-model")
    provider = _ClosableFake(model="gemini-embedding-001")

    code = _reindex(config_dir, monkeypatch, provider)

    out = capsys.readouterr().out
    assert code == 0
    assert "old-model → gemini-embedding-001" in out
    assert "Chunks to embed: 1 in 1 batches" in out
    assert "1 vectors, 1 versions, 1 newly embedded" in out


def test_reindex_provider_failure_exits_1_with_arabic_message_and_resume_hint(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest(config_dir, "old-model")
    provider = _ClosableFake(
        model="gemini-embedding-001", failures=[ProviderAuthError("GEMINI_API_KEY is not set")]
    )

    code = _reindex(config_dir, monkeypatch, provider)

    err = capsys.readouterr().err
    assert code == 1
    assert "PROVIDER_AUTH" in err and "مفتاح" in err
    assert "GEMINI_API_KEY is not set" in err
    assert "run `rag reindex` again" in err
    assert provider.closed


def test_reindex_interrupted_by_ctrl_c_exits_130(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest(config_dir, "old-model")
    provider = _ClosableFake(model="gemini-embedding-001", failures=[KeyboardInterrupt()])  # type: ignore[list-item]

    code = _reindex(config_dir, monkeypatch, provider)

    assert code == 130
    assert "Interrupted" in capsys.readouterr().out
