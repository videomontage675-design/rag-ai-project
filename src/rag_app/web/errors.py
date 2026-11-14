"""Translate errors into the JSON error contract of DESIGN-001 §11.1 (and HTML for pages)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from rag_app.core.errors import CATALOG, AppError, ErrorCode

logger = logging.getLogger(__name__)


def error_body(
    code: ErrorCode, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build the JSON error shape: ``{"error": {"code", "message", "details"}}``."""
    return {"error": {"code": str(code), "message": message, "details": details or {}}}


def error_response(
    request: Request,
    code: ErrorCode,
    message: str,
    details: dict[str, object] | None = None,
    status_code: int | None = None,
) -> Response:
    """Return the error in the shape the caller understands, keeping the HTTP status.

    API clients get the JSON contract. HTMX requests from the UI get an Arabic alert fragment
    that is retargeted into the page's alert region, so every action reports errors the same
    way without page-specific code (FR-UI-07).
    """
    status_code = status_code or CATALOG[code].http_status
    if request.headers.get("hx-request") == "true":
        templates: Jinja2Templates = request.app.state.context.templates
        return templates.TemplateResponse(
            request,
            "partials/alert.html",
            {"kind": "error", "message": message, "code": str(code)},
            status_code=status_code,
            headers={"HX-Retarget": "#alerts", "HX-Reswap": "innerHTML"},
        )
    return JSONResponse(error_body(code, message, details), status_code)


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every failure leaves the app in the same, documented shape."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> Response:
        logger.info("app_error", extra={"code": str(exc.code)})
        return error_response(request, exc.code, exc.message_ar, dict(exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        fields = [".".join(str(p) for p in err["loc"]) for err in exc.errors()]
        spec = CATALOG[ErrorCode.VALIDATION_ERROR]
        return error_response(
            request, ErrorCode.VALIDATION_ERROR, spec.message_ar, {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.VALIDATION_ERROR
        return error_response(request, code, CATALOG[code].message_ar, None, exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled_exception", extra={"exception_type": type(exc).__name__})
        spec = CATALOG[ErrorCode.INTERNAL_ERROR]
        return error_response(request, ErrorCode.INTERNAL_ERROR, spec.message_ar)
