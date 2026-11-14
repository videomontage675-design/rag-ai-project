"""Translate errors into the JSON error contract of DESIGN-001 §11.1 (and HTML for pages)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from rag_app.core.errors import CATALOG, AppError, ErrorCode

logger = logging.getLogger(__name__)


def error_body(
    code: ErrorCode, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build the JSON error shape: ``{"error": {"code", "message", "details"}}``."""
    return {"error": {"code": str(code), "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every failure leaves the app in the same, documented shape."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> Response:
        logger.info("app_error", extra={"code": str(exc.code)})
        return JSONResponse(error_body(exc.code, exc.message_ar, exc.details), exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> Response:
        fields = [".".join(str(p) for p in err["loc"]) for err in exc.errors()]
        spec = CATALOG[ErrorCode.VALIDATION_ERROR]
        return JSONResponse(
            error_body(ErrorCode.VALIDATION_ERROR, spec.message_ar, {"fields": fields}),
            spec.http_status,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> Response:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.VALIDATION_ERROR
        return JSONResponse(error_body(code, CATALOG[code].message_ar), exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> Response:
        logger.exception("unhandled_exception", extra={"exception_type": type(exc).__name__})
        spec = CATALOG[ErrorCode.INTERNAL_ERROR]
        return JSONResponse(error_body(ErrorCode.INTERNAL_ERROR, spec.message_ar), spec.http_status)
