"""HTML pages. Phase 5 provides the shell; chat and document pages arrive in Phase 10."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from rag_app.services.system import get_system_status
from rag_app.web.context import AppContext, get_context

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, ctx: Annotated[AppContext, Depends(get_context)]) -> HTMLResponse:
    """Welcome page with the domain profile's text and example questions (FR-UI-08)."""
    status = get_system_status(ctx.settings, ctx.db)
    return ctx.templates.TemplateResponse(
        request, "index.html", {"profile": ctx.profile, "status": status}
    )
