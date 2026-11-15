"""Composition root of the web application: builds every dependency exactly once.

Wiring happens here and nowhere else (STD-001 §4), so a dependency can be replaced, e.g. a
different provider or a test database, without touching the code that uses it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import rag_app
from rag_app.config.domain_profile import load_domain_profile
from rag_app.config.settings import Settings
from rag_app.providers.factory import open_embedding_provider
from rag_app.providers.ports import EmbeddingProvider
from rag_app.services.documents import DocumentService
from rag_app.services.ingestion_worker import IngestionWorker
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.migrate import apply_migrations
from rag_app.web.api import documents as documents_api
from rag_app.web.api import system
from rag_app.web.context import AppContext
from rag_app.web.errors import install_error_handlers
from rag_app.web.middleware import local_only_guard, request_context, upload_size_guard
from rag_app.web.ui import format as ui_format
from rag_app.web.ui import pages

logger = logging.getLogger(__name__)
_WEB_DIR = Path(__file__).parent


def create_app(settings: Settings, *, embedder: EmbeddingProvider | None = None) -> FastAPI:
    """Build the FastAPI application for ``settings``.

    The database schema is migrated at start-up, so a fresh data folder works immediately.
    ``embedder`` replaces the configured embedding provider (tests pass a fake, so no test
    reaches a real provider).
    """
    profile = load_domain_profile(settings.resolve(settings.domain_profile_file))
    db = Database(settings.database_file)
    templates = Jinja2Templates(directory=_WEB_DIR / "templates")
    ui_format.register(templates.env)
    files = FileStore(settings.uploads_dir)
    adapter = None
    if embedder is None:
        adapter = open_embedding_provider(settings.providers.embedding)
        embedder = adapter
    worker = IngestionWorker(settings, db, files, embedder)
    documents = DocumentService(settings, db, files, on_enqueued=worker.wake)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        applied = apply_migrations(db)
        removed = documents.sweep_orphan_files()
        worker.recover()
        if settings.ingestion.run_worker:
            worker.start()
        logger.info(
            "app_started",
            extra={
                "migrations_applied": applied,
                "orphan_files_removed": len(removed),
                "version": rag_app.__version__,
            },
        )
        try:
            yield
        finally:
            worker.stop()
            if adapter is not None:
                adapter.close()
            logger.info("app_stopped")

    app = FastAPI(
        title="Dafira RAG Assistant API",
        version=rag_app.__version__,
        description="Arabic question answering over a private document knowledge base.",
        lifespan=lifespan,
    )
    app.state.context = AppContext(
        settings=settings,
        profile=profile,
        db=db,
        templates=templates,
        documents=documents,
        worker=worker,
    )
    # Registered last = outermost: foreign hosts and origins are refused first, then
    # oversized uploads, before any request body is read.
    app.middleware("http")(request_context)
    app.middleware("http")(upload_size_guard(settings.limits.max_upload_mb * 1024 * 1024))
    app.middleware("http")(
        local_only_guard(enforce_loopback_host=not settings.server.allow_non_local)
    )
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")
    app.include_router(system.health_router)
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(documents_api.router, prefix="/api/v1")
    app.include_router(pages.router)
    return app
