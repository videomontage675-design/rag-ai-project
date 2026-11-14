"""Shared fixtures: an isolated settings file and data folder per test (never the real one)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rag_app.config.settings import Settings, load_settings
from rag_app.storage.db import Database
from rag_app.storage.migrate import apply_migrations
from rag_app.web.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of the real config folder, with the data folder redirected into ``tmp_path``."""
    target = tmp_path / "config"
    shutil.copytree(PROJECT_ROOT / "config", target)
    settings_file = target / "settings.toml"
    text = settings_file.read_text(encoding="utf-8")
    settings_file.write_text(
        text.replace('data_dir = "../app_data"', 'data_dir = "../data"'), encoding="utf-8"
    )
    return target


@pytest.fixture
def settings(config_dir: Path) -> Settings:
    return load_settings(config_dir / "settings.toml")


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings.database_file)
    apply_migrations(database)
    return database


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
