"""One adapter for every OpenAI-compatible embeddings endpoint: Gemini, a local server, … (T-13).

Phase 3 findings handled here:
- Gemini's compatible endpoint omits ``index`` in results, so order is taken from the list;
- free tiers return 429 per minute, so batches are throttled and retried with backoff;
- ``dimensions`` (D-039) returns unnormalized vectors, so every vector is L2-normalized here.

Texts are never logged (NFR-PRV-02); only counts, status codes, and timings are.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from rag_app.config.settings import ProviderSettings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.providers.ports import EmbeddingTask, Vectors

logger = logging.getLogger(__name__)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How patiently to retry rate limits and transient failures."""

    max_attempts: int = 5
    first_backoff_seconds: float = 15.0


class OpenAICompatibleEmbeddings:
    """``POST {base_url}/embeddings`` with batching, throttling, retries, and normalization."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        api_key: str | None,
        retry: RetryPolicy,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure the adapter; ``transport`` and ``sleep`` are replaceable for tests."""
        self._settings = settings
        self._retry = retry
        self._sleep = sleep
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=settings.base_url,
            headers=headers,
            timeout=settings.timeout_seconds,
            transport=transport,
        )
        self._last_batch_at: float | None = None

    @property
    def model(self) -> str:
        """Model identifier stored with every vector."""
        return self._settings.model

    @property
    def dimensions(self) -> int | None:
        """Requested vector size (D-039)."""
        return self._settings.dimensions

    def embed(self, texts: list[str], task: EmbeddingTask) -> Vectors:
        """Embed texts in batches; ``task`` is accepted for the port but this API has none."""
        del task  # the OpenAI-compatible API has no query/document task type (TECH-001 T-10)
        if not texts:
            return np.zeros((0, self.dimensions or 0), dtype=np.float32)
        size = self._settings.batch_size
        rows = [self._embed_batch(texts[i : i + size]) for i in range(0, len(texts), size)]
        return np.vstack(rows)

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    # ------------------------------------------------------------------ internals
    def _throttle(self) -> None:
        gap = self._settings.min_seconds_between_batches
        if self._last_batch_at is not None and gap > 0:
            wait = gap - (time.monotonic() - self._last_batch_at)
            if wait > 0:
                self._sleep(wait)
        self._last_batch_at = time.monotonic()

    def _embed_batch(self, texts: list[str]) -> Vectors:
        body: dict[str, Any] = {"model": self.model, "input": texts, **self._settings.extra_body}
        if self.dimensions:
            body["dimensions"] = self.dimensions
        payload = self._post_with_retry(body)
        return self._parse(payload, expected=len(texts))

    def _post_with_retry(self, body: dict[str, Any]) -> Any:  # noqa: ANN401  (JSON)
        backoff = self._retry.first_backoff_seconds
        status: int | None = None
        response: httpx.Response | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            self._throttle()
            started = time.monotonic()
            try:
                response = self._client.post("/embeddings", json=body)
            except httpx.TransportError:  # timeouts, refused connections, resets
                status, response = None, None
            else:
                status = response.status_code
                if status == 200:
                    logger.info(
                        "provider_call",
                        extra={
                            "model": self.model,
                            "inputs": len(body["input"]),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                        },
                    )
                    return response.json()
                if status in (401, 403):
                    raise AppError(ErrorCode.PROVIDER_AUTH, details={"status": status})
                if status not in _RETRYABLE:
                    raise AppError(
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        details={"status": status, "model": self.model},
                    )
            if attempt == self._retry.max_attempts:
                break
            wait = _retry_after(response) if response is not None and status == 429 else None
            wait = min(wait if wait is not None else backoff, _MAX_BACKOFF_SECONDS)
            logger.warning(
                "provider_retry",
                extra={"model": self.model, "status": status, "attempt": attempt, "wait_s": wait},
            )
            self._sleep(wait)
            backoff *= 2
        code = ErrorCode.PROVIDER_RATE_LIMITED if status == 429 else ErrorCode.PROVIDER_UNAVAILABLE
        raise AppError(code, details={"status": status, "attempts": self._retry.max_attempts})

    def _parse(self, payload: Any, *, expected: int) -> Vectors:  # noqa: ANN401  (JSON)
        try:
            items = payload["data"]
            if all("index" in item for item in items):
                items = sorted(items, key=lambda item: item["index"])
            vectors = np.asarray([item["embedding"] for item in items], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE, details={"reason": "malformed response"}
            ) from exc
        if vectors.ndim != 2 or len(vectors) != expected:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                details={"reason": "wrong number of vectors", "expected": expected},
            )
        if self.dimensions and vectors.shape[1] != self.dimensions:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                details={"reason": "wrong dimension", "got": int(vectors.shape[1])},
            )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.all(norms > 0):
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE, details={"reason": "zero vector"})
        normalized: Vectors = (vectors / norms).astype(np.float32)
        return normalized


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric ``Retry-After`` header, if the provider sent one."""
    value = response.headers.get("retry-after", "")
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def build_embedder(settings: ProviderSettings, retry: RetryPolicy) -> OpenAICompatibleEmbeddings:
    """Create the configured embedding adapter, reading the key from the environment.

    Raises:
        AppError: ``PROVIDER_AUTH`` when the configured key variable is empty.
    """
    key = os.environ.get(settings.api_key_env, "") if settings.api_key_env else None
    if settings.api_key_env and not key:
        raise AppError(ErrorCode.PROVIDER_AUTH, details={"missing": settings.api_key_env})
    return OpenAICompatibleEmbeddings(settings, api_key=key, retry=retry)
