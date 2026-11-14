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
from rag_app.storage.db import Database
from rag_app.storage.migrate import apply_migrations
from rag_app.web.api import system
from rag_app.web.context import AppContext
from rag_app.web.errors import install_error_handlers
from rag_app.web.middleware import request_context
from rag_app.web.ui import pages

logger = logging.getLogger(__name__)
_WEB_DIR = Path(__file__).parent


def create_app(settings: Settings) -> FastAPI:
    """Build the FastAPI application for ``settings``.

    The database schema is migrated at start-up, so a fresh data folder works immediately.
    """
    profile = load_domain_profile(settings.resolve(settings.domain_profile_file))
    db = Database(settings.database_file)
    templates = Jinja2Templates(directory=_WEB_DIR / "templates")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        applied = apply_migrations(db)
        logger.info(
            "app_started", extra={"migrations_applied": applied, "version": rag_app.__version__}
        )
        yield
        logger.info("app_stopped")

    app = FastAPI(
        title="Dafira RAG Assistant API",
        version=rag_app.__version__,
        description="Arabic question answering over a private document knowledge base.",
        lifespan=lifespan,
    )
    app.state.context = AppContext(settings=settings, profile=profile, db=db, templates=templates)
    app.middleware("http")(request_context)
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")
    app.include_router(system.health_router)
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(pages.router)
    return app
