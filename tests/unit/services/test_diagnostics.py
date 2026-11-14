from pathlib import Path

import pytest

from rag_app.config.settings import Settings
from rag_app.services.diagnostics import CheckLevel, run_checks

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
