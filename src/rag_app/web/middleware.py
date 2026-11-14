"""HTTP middleware: request correlation (``X-Request-ID``) and the upload size guard."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

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


# ---------------------------------------------------------------------------- local-only guard
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Same-origin only; no inline script (app.js uses event listeners); styles from our files only.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _host_name(netloc: str) -> str:
    """``host[:port]`` → host, keeping IPv6 brackets (``[::1]:8000`` → ``[::1]``)."""
    if netloc.startswith("["):
        return netloc.split("]", 1)[0] + "]"
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def _is_foreign(request: Request, *, enforce_loopback_host: bool) -> bool:
    host = request.headers.get("host", "")
    if enforce_loopback_host and _host_name(host).lower() not in _LOOPBACK_HOSTS:
        return True  # DNS rebinding: a foreign name pointing at 127.0.0.1
    if request.method not in _UNSAFE_METHODS:
        return False
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")  # "null" from sandboxed pages is foreign too
    return origin is not None and urlsplit(origin).netloc != host


def local_only_guard(*, enforce_loopback_host: bool) -> Middleware:
    """Keep a login-free app reachable only from this machine's own pages (CLAUDE.md §12).

    Listening on 127.0.0.1 stops other computers, but not a web page open in the user's
    browser. Two browser-based attacks are blocked here:

    - DNS rebinding: a foreign domain resolved to 127.0.0.1 arrives with a foreign ``Host``,
      so any non-loopback ``Host`` is refused (unless the owner explicitly allowed
      non-local access, which is then their decision).
    - Cross-site requests (CSRF): a state-changing request whose ``Origin`` is not this
      app, or that the browser marks ``Sec-Fetch-Site: cross-site``, is refused. Tools such
      as curl send neither header and keep working.

    Every response also carries the security headers above.
    """
    from rag_app.web.errors import error_response  # avoids an import cycle

    def refuse(request: Request) -> Response:
        message = AppError(ErrorCode.FORBIDDEN_ORIGIN).message_ar
        logger.warning(
            "request_refused",
            extra={"host": request.headers.get("host", ""), "path": request.url.path},
        )
        return error_response(request, ErrorCode.FORBIDDEN_ORIGIN, message)

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if _is_foreign(request, enforce_loopback_host=enforce_loopback_host):
            response = refuse(request)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    return guard
