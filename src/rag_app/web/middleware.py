"""HTTP middleware: request correlation (``X-Request-ID``) and the upload size guard."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from rag_app.core.errors import AppError, ErrorCode
from rag_app.core.ids import new_id
from rag_app.core.logging import request_id_var

logger = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a request id (client-supplied if well-formed), time the request, and log it."""
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _SAFE_ID.match(incoming) else new_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


# Multipart framing (boundaries, part headers) is small; this margin keeps a file of exactly
# the maximum size acceptable while still refusing anything clearly too large.
_MULTIPART_MARGIN = 64 * 1024

Middleware = Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]


def upload_size_guard(max_bytes: int) -> Middleware:
    """Refuse an upload by its ``Content-Length`` before the body is read (NFR-PRF-04).

    The framework would otherwise spool the whole body to disk first. Uploads without a
    length (chunked) are still limited while streaming, by the FileStore.
    """
    from rag_app.web.errors import error_response

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length", "")
        if (
            request.method == "POST"
            and request.headers.get("content-type", "").startswith("multipart/form-data")
            and length.isdigit()
            and int(length) > max_bytes + _MULTIPART_MARGIN
        ):
            limit_mb = max_bytes // (1024 * 1024)
            message = AppError(ErrorCode.FILE_TOO_LARGE, limit_mb=limit_mb).message_ar
            return error_response(request, ErrorCode.FILE_TOO_LARGE, message)
        return await call_next(request)

    return guard
