from pathlib import Path

import pytest

from rag_app.config.settings import load_settings
from rag_app.core.errors import AppError, ErrorCode

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "settings.toml"
    file.write_text(body, encoding="utf-8")
    return file


PROVIDERS = """
[providers.embedding]
base_url = "https://example.com/v1"
model = "emb"
[providers.chat]
base_url = "https://example.com/v1"
model = "chat"
"""


def test_project_settings_file_is_valid() -> None:
    settings = load_settings(Path("config/settings.toml"))

    assert settings.server.host == "127.0.0.1"
    assert settings.limits.max_upload_mb == 10


def test_relative_data_dir_is_resolved_against_settings_folder(tmp_path: Path) -> None:
    settings = load_settings(_write(tmp_path, PROVIDERS))

    assert settings.data_dir == (tmp_path / "../app_data").resolve()


def test_missing_file_raises_config_invalid(tmp_path: Path) -> None:
    with pytest.raises(AppError) as info:
        load_settings(tmp_path / "missing.toml")

    assert info.value.code is ErrorCode.CONFIG_INVALID


def test_non_loopback_host_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="loopback"):
        load_settings(_write(tmp_path, '[server]\nhost = "0.0.0.0"\n' + PROVIDERS))


def test_unknown_key_is_rejected_to_catch_typos(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="chunk_charz"):
        load_settings(_write(tmp_path, "[rag]\nchunk_charz = 800\n" + PROVIDERS))


def test_overlap_not_smaller_than_chunk_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="chunk_overlap"):
        load_settings(
            _write(tmp_path, "[rag]\nchunk_chars = 200\nchunk_overlap = 200\n" + PROVIDERS)
        )


def test_plain_http_provider_is_rejected_except_localhost(tmp_path: Path) -> None:
    body = PROVIDERS.replace(
        'base_url = "https://example.com/v1"\nmodel = "chat"',
        'base_url = "http://example.com/v1"\nmodel = "chat"',
    )
    with pytest.raises(AppError, match="base_url"):
        load_settings(_write(tmp_path, body))

    local = PROVIDERS.replace(
        'base_url = "https://example.com/v1"\nmodel = "chat"',
        'base_url = "http://localhost:11434/v1"\nmodel = "chat"',
    )
    assert load_settings(_write(tmp_path, local)).providers.chat.base_url.startswith(
        "http://localhost"
    )
