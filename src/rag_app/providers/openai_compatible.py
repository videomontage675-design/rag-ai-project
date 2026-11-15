"""OpenAI-compatible embeddings adapter (T-13): one class for Gemini, Cohere, or a local server.

Only ``base_url``, ``model``, and the key variable change between providers (D-010, D-013).
The adapter converts every HTTP outcome into a typed :class:`ProviderError` and validates the
response before anything else sees it, because a malformed vector stored once would corrupt
retrieval silently.

Logs and errors carry the HTTP status and the provider's error *type* only, never the request
texts or the provider's message, which can echo input (STD-001 §8).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

import httpx

from rag_app.config.settings import ProviderSettings
from rag_app.domain.models import EmbeddingTask
from rag_app.providers.ports import (
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)

# Gemini answers an invalid key with HTTP 400 INVALID_ARGUMENT and this reason, not with 401.
_INVALID_KEY_MARKERS = ("API_KEY_INVALID", "API key not valid")


class OpenAICompatibleEmbeddings:
    """Calls ``POST {base_url}/embeddings`` with ``{"model", "input"}``.

    The OpenAI request shape has no task field, so ``task`` is not sent; the Phase 3 benchmark
    measured ``gemini-embedding-001`` through exactly this endpoint (T-10). Provider-specific
    options go in ``extra_body`` (DESIGN-001 §10).
    """

    def __init__(
        self,
        cfg: ProviderSettings,
        *,
        api_key: str | None,
        client: httpx.Client | None = None,
    ) -> None:
        """Bind the adapter to one endpoint and model. ``api_key`` comes from the environment."""
        self._cfg = cfg
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=cfg.timeout_seconds)

    @property
    def model(self) -> str:
        """The configured model identifier."""
        return self._cfg.model

    def close(self) -> None:
        """Release pooled connections."""
        self._client.close()

    def embed(self, texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        """Embed ``texts`` in one request; see :meth:`EmbeddingProvider.embed`."""
        del task  # not part of the OpenAI request shape (see class docstring)
        if not texts:
            return []
        if self._cfg.api_key_env and not self._api_key:
            raise ProviderAuthError(f"{self._cfg.api_key_env} is not set")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {**self._cfg.extra_body, "model": self._cfg.model, "input": list(texts)}
        try:
            response = self._client.post(
                f"{self._cfg.base_url}/embeddings", json=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(f"network: {type(exc).__name__}") from exc
        if response.status_code != httpx.codes.OK:
            raise _status_error(response)
        return _parse_vectors(response, expected=len(texts))


def _status_error(response: httpx.Response) -> ProviderError:
    """Map a non-200 response to a typed error (DESIGN-001 §10)."""
    status = response.status_code
    reason = f"HTTP {status} {_error_type(response)}".rstrip()
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return ProviderRateLimitedError(
            reason, status=status, retry_after=_retry_after(response.headers.get("retry-after"))
        )
    if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN) or (
        status == httpx.codes.BAD_REQUEST
        and any(marker in response.text for marker in _INVALID_KEY_MARKERS)
    ):
        return ProviderAuthError(reason, status=status)
    if status == httpx.codes.NOT_FOUND:
        # The model was retired or renamed (seen in Phase 3); retrying cannot help.
        return ProviderUnavailableError(reason, status=status, retryable=False)
    if status == httpx.codes.REQUEST_TIMEOUT or status >= httpx.codes.INTERNAL_SERVER_ERROR:
        return ProviderUnavailableError(reason, status=status)
    return ProviderBadResponseError(reason, status=status)


def _error_type(response: httpx.Response) -> str:
    """The provider's machine-readable error type (e.g. ``RESOURCE_EXHAUSTED``), if any."""
    try:
        payload: Any = response.json()  # Any: untrusted JSON, narrowed below
    except ValueError:
        return ""
    if isinstance(payload, list) and payload:  # Gemini sometimes wraps the error in a list
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    for key in ("status", "type", "code"):
        value = error.get(key)
        if isinstance(value, str) and value.replace("_", "").isalnum():
            return value[:60]
    return ""


def _retry_after(value: str | None) -> float | None:
    """Seconds from a ``Retry-After`` header; the HTTP-date form is ignored (rare in APIs)."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _parse_vectors(response: httpx.Response, expected: int) -> list[list[float]]:
    """Validate an embeddings response and return the vectors in input order."""
    try:
        payload: Any = response.json()  # Any: untrusted JSON, validated item by item below
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderBadResponseError("body is not JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != expected:
        got = len(data) if isinstance(data, list) else "no"
        raise ProviderBadResponseError(f"expected {expected} vectors, got {got}")
    if not all(isinstance(item, dict) for item in data):
        raise ProviderBadResponseError("data items are not objects")
    # Gemini omits "index" and returns items in input order (Phase 3 finding); OpenAI-style
    # servers include it and may reorder.
    if all("index" in item for item in data):
        if sorted(item["index"] for item in data) != list(range(expected)):
            raise ProviderBadResponseError("indexes do not match the inputs")
        data = sorted(data, key=lambda item: item["index"])
    vectors = [_vector(item.get("embedding")) for item in data]
    if len({len(v) for v in vectors}) != 1:
        raise ProviderBadResponseError("vectors have different lengths")
    return vectors


def _vector(value: object) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ProviderBadResponseError("embedding is missing or empty")
    # bool is an int subclass; a list of booleans is not a vector.
    if not all(isinstance(x, int | float) and not isinstance(x, bool) for x in value):
        raise ProviderBadResponseError("embedding holds non-numeric values")
    vector = [float(x) for x in value]
    if not all(math.isfinite(x) for x in vector):
        raise ProviderBadResponseError("embedding holds non-finite values")
    return vector
