"""Retries and throttling around an embedding provider (FR-ING-11, DESIGN-001 §10).

Free tiers enforce per-minute quotas: Phase 3 hit HTTP 429 while embedding in batches, and
throttling with backoff resolved it (TECH-001). The wrappers keep that policy out of both the
HTTP adapter and the pipeline:

* :class:`ThrottledEmbeddings` spaces requests at least ``min_interval`` seconds apart;
* :class:`RetryingEmbeddings` retries retryable failures with exponential backoff.

Compose them as ``RetryingEmbeddings(ThrottledEmbeddings(adapter))``, so every attempt,
including a retry, respects the spacing. ``sleep`` is injected: tests pass a recorder, and the
ingestion worker passes a sleep that its shutdown can interrupt.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rag_app.domain.models import EmbeddingTask
from rag_app.providers.ports import EmbeddingProvider, ProviderError

logger = logging.getLogger(__name__)

Sleep = Callable[[float], None]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff: waits ``initial``, ``initial * multiplier``, … up to ``maximum``.

    ``attempts`` counts the first call, so ``attempts = 5`` means up to four retries.
    """

    attempts: int
    initial_seconds: float
    multiplier: float = 2.0
    maximum_seconds: float = 300.0

    def delay(self, retry_number: int) -> float:
        """Seconds to wait before retry ``retry_number`` (1-based)."""
        return min(
            self.initial_seconds * self.multiplier ** (retry_number - 1), self.maximum_seconds
        )


class RetryingEmbeddings:
    """Retries calls that fail with a retryable :class:`ProviderError`."""

    def __init__(self, inner: EmbeddingProvider, policy: RetryPolicy, sleep: Sleep) -> None:
        """Wrap ``inner``; ``sleep`` performs the waits."""
        self._inner = inner
        self._policy = policy
        self._sleep = sleep

    @property
    def model(self) -> str:
        """The wrapped provider's model."""
        return self._inner.model

    def embed(self, texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        """Call the provider, waiting and retrying on transient failures.

        Raises:
            ProviderError: the last failure, once retries are exhausted or it is permanent.
        """
        for attempt in range(1, self._policy.attempts + 1):
            try:
                return self._inner.embed(texts, task)
            except ProviderError as exc:
                if not exc.retryable or attempt == self._policy.attempts:
                    raise
                # Honour Retry-After when it asks for longer than our own schedule.
                wait = min(
                    max(self._policy.delay(attempt), exc.retry_after or 0.0),
                    self._policy.maximum_seconds,
                )
                logger.warning(
                    "provider_retry",
                    extra={
                        "model": self.model,
                        "attempt": attempt,
                        "error_code": exc.code.value,
                        "reason": exc.reason,
                        "wait_seconds": wait,
                    },
                )
                self._sleep(wait)
        msg = "unreachable: the loop returns or raises"  # pragma: no cover
        raise AssertionError(msg)  # pragma: no cover


class ThrottledEmbeddings:
    """Keeps at least ``min_interval`` seconds between the starts of consecutive requests."""

    def __init__(
        self,
        inner: EmbeddingProvider,
        min_interval: float,
        sleep: Sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        """Wrap ``inner``. ``clock`` must be monotonic, so wall-clock changes do not matter."""
        self._inner = inner
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_start: float | None = None
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        """The wrapped provider's model."""
        return self._inner.model

    def embed(self, texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        """Wait if the previous request started too recently, then call the provider."""
        with self._lock:
            if self._last_start is not None:
                wait = self._last_start + self._min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
            self._last_start = self._clock()
            return self._inner.embed(texts, task)


def resilient(
    provider: EmbeddingProvider,
    *,
    retry: RetryPolicy,
    min_interval: float,
    sleep: Sleep,
    clock: Clock = time.monotonic,
) -> EmbeddingProvider:
    """Wrap ``provider`` with throttling inside retries (see the module docstring)."""
    throttled = ThrottledEmbeddings(provider, min_interval, sleep, clock)
    return RetryingEmbeddings(throttled, retry, sleep)
