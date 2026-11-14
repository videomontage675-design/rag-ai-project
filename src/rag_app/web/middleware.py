"""Request correlation: every request gets an ``X-Request-ID`` used in all of its log lines."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

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
