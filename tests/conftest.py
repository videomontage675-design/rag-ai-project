"""Shared fixtures: an isolated settings file and data folder per test (never the real one)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.config.settings import Settings, load_settings
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.migrate import apply_migrations
from rag_app.web.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL = "http://127.0.0.1:8000"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A copy of the real config folder: data folder in ``tmp_path``, no worker, no throttling.

    Throttling is turned off so tests never wait between embedding batches; the throttle
    itself is tested on its own with a fake clock.
    """
    target = tmp_path / "config"
    shutil.copytree(PROJECT_ROOT / "config", target)
    settings_file = target / "settings.toml"
    text = settings_file.read_text(encoding="utf-8")
    settings_file.write_text(
        text.replace('data_dir = "../app_data"', 'data_dir = "../data"')
        .replace("[ingestion]\n", "[ingestion]\nrun_worker = false\n")
        .replace("min_seconds_between_batches = 20", "min_seconds_between_batches = 0"),
        encoding="utf-8",
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
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def client(settings: Settings, embedder: FakeEmbeddingProvider) -> Iterator[TestClient]:
    # The app only answers loopback host names (local-only guard).
    with TestClient(create_app(settings, embedder=embedder), base_url=LOCAL) as test_client:
        yield test_client


@pytest.fixture
def files(settings: Settings) -> FileStore:
    return FileStore(settings.uploads_dir)


@pytest.fixture
def worker(
    settings: Settings, db: Database, files: FileStore, embedder: FakeEmbeddingProvider
) -> IngestionWorker:
    return IngestionWorker(settings, db, files, embedder)


@pytest.fixture
def documents(
    settings: Settings, db: Database, files: FileStore, worker: IngestionWorker
) -> DocumentService:
    return DocumentService(settings, db, files, on_enqueued=worker.wake)
