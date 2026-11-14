"""Per-application objects shared by request handlers (built once in :func:`create_app`)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.templating import Jinja2Templates

from rag_app.config.domain_profile import DomainProfile
from rag_app.config.settings import Settings
from rag_app.storage.db import Database


@dataclass(frozen=True, slots=True)
class AppContext:
    """Dependencies wired at start-up; the composition root is :mod:`rag_app.web.app`."""

    settings: Settings
    profile: DomainProfile
    db: Database
    templates: Jinja2Templates


def get_context(request: Request) -> AppContext:
    """FastAPI dependency returning the application context."""
    context: AppContext = request.app.state.context
    return context
