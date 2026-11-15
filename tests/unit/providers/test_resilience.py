"""Retries and throttling around a provider, with a fake clock (no real waiting)."""

from __future__ import annotations

import pytest
from fakes.embeddings import FakeEmbeddingProvider

from rag_app.domain.models import EmbeddingTask
from rag_app.providers.ports import (
    ProviderAuthError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)
from rag_app.providers.resilience import (
    RetryingEmbeddings,
    RetryPolicy,
    ThrottledEmbeddings,
    resilient,
)

pytestmark = pytest.mark.unit

DOC = EmbeddingTask.DOCUMENT


class FakeClock:
    """A monotonic clock that only moves when someone sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_retry_policy_doubles_up_to_the_maximum() -> None:
    policy = RetryPolicy(attempts=6, initial_seconds=15, maximum_seconds=100)

    assert [policy.delay(n) for n in range(1, 6)] == [15, 30, 60, 100, 100]


def test_retries_transient_failures_with_backoff_then_succeeds() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider(
        failures=[ProviderRateLimitedError("429"), ProviderUnavailableError("503")]
    )
    provider = RetryingEmbeddings(inner, RetryPolicy(5, 15), clock.sleep)

    vectors = provider.embed(["a"], DOC)

    assert len(vectors) == 1
    assert clock.sleeps == [15, 30]
    assert len(inner.calls) == 3
    assert provider.model == inner.model


def test_gives_up_after_the_last_attempt_with_the_last_error() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider(failures=[ProviderUnavailableError(str(i)) for i in range(5)])
    provider = RetryingEmbeddings(inner, RetryPolicy(3, 1), clock.sleep)

    with pytest.raises(ProviderUnavailableError) as info:
        provider.embed(["a"], DOC)

    assert info.value.reason == "2"
    assert len(inner.calls) == 3
    assert clock.sleeps == [1, 2]


def test_permanent_failures_are_not_retried() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider(
        failures=[ProviderAuthError("bad key"), ProviderUnavailableError("404", retryable=False)]
    )
    provider = RetryingEmbeddings(inner, RetryPolicy(5, 1), clock.sleep)

    with pytest.raises(ProviderAuthError):
        provider.embed(["a"], DOC)
    with pytest.raises(ProviderUnavailableError):
        provider.embed(["a"], DOC)

    assert clock.sleeps == []


def test_retry_after_longer_than_the_schedule_is_honoured_within_the_maximum() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider(
        failures=[
            ProviderRateLimitedError("429", retry_after=40),
            ProviderRateLimitedError("429", retry_after=1),
            ProviderRateLimitedError("429", retry_after=9999),
        ]
    )
    provider = RetryingEmbeddings(inner, RetryPolicy(4, 15, maximum_seconds=120), clock.sleep)

    provider.embed(["a"], DOC)

    assert clock.sleeps == [40, 30, 120]


def test_throttle_spaces_request_starts_and_never_waits_needlessly() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider()
    provider = ThrottledEmbeddings(inner, 20, clock.sleep, clock)

    provider.embed(["a"], DOC)  # first call: no wait
    clock.now += 5
    provider.embed(["b"], DOC)  # 5 s later: waits 15 s
    clock.now += 30
    provider.embed(["c"], DOC)  # 30 s later: no wait

    assert clock.sleeps == [15]
    assert provider.model == inner.model


def test_resilient_throttles_every_retry_attempt_too() -> None:
    clock = FakeClock()
    inner = FakeEmbeddingProvider(failures=[ProviderRateLimitedError("429")])
    provider = resilient(
        inner, retry=RetryPolicy(3, 5), min_interval=20, sleep=clock.sleep, clock=clock
    )

    provider.embed(["a"], DOC)

    # backoff 5 s, then the throttle adds 15 s so the retry starts 20 s after the first call
    assert clock.sleeps == [5, 15]
