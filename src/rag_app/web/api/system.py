"""Health and system-status endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

import rag_app
from rag_app.services.system import get_system_status
from rag_app.web.api.schemas import HealthResponse, SystemStatusResponse
from rag_app.web.context import AppContext, get_context

health_router = APIRouter(tags=["system"])
router = APIRouter(prefix="/system", tags=["system"])


@health_router.get("/health")
def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok", version=rag_app.__version__)


@router.get("/status")
def system_status(ctx: Annotated[AppContext, Depends(get_context)]) -> SystemStatusResponse:
    """Counts, index model, re-index need, and providers (never keys or key variable names)."""
    return SystemStatusResponse.model_validate(asdict(get_system_status(ctx.settings, ctx.db)))
