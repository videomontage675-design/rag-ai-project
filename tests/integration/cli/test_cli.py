from pathlib import Path

import pytest

from rag_app.cli import main

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
