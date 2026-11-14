"""OpenAI-compatible embeddings adapter against a mocked HTTP transport (NFR-MNT-02)."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from rag_app.config.settings import ProviderSettings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.providers.openai_compatible import (
    OpenAICompatibleEmbeddings,
    RetryPolicy,
    build_embedder,
)

pytestmark = pytest.mark.unit


def _settings(**over: object) -> ProviderSettings:
    base = {
        "base_url": "https://api.example.test/v1",
        "model": "m",
        "dimensions": 3,
        "batch_size": 2,
    }
    return ProviderSettings.model_validate({**base, **over})


def _vec(text: str) -> list[float]:
    return [float(len(text)), 2.0, 0.0]  # deliberately unnormalized


def _ok(
    request: httpx.Request, *, with_index: bool = True, reverse: bool = False
) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    data = [
        {"embedding": _vec(t), **({"index": i} if with_index else {})} for i, t in enumerate(texts)
    ]
    return httpx.Response(200, json={"data": data[::-1] if reverse else data})


class Recorder:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item  # type: ignore[return-value]


def _adapter(handler: Recorder, sleeps: list[float], **over: object) -> OpenAICompatibleEmbeddings:
    return OpenAICompatibleEmbeddings(
        _settings(**over),
        api_key="k-123",
        retry=RetryPolicy(max_attempts=3, first_backoff_seconds=1.0),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )


def test_batches_keep_order_and_vectors_are_normalized() -> None:
    handler = Recorder(lambda r: _ok(r, reverse=True))  # results out of order, with index
    sleeps: list[float] = []

    out = _adapter(handler, sleeps).embed(["a", "bb", "ccc"], "document")

    assert [b["input"] for b in handler.bodies] == [["a", "bb"], ["ccc"]]
    assert all(b["dimensions"] == 3 and b["model"] == "m" for b in handler.bodies)
    assert handler.headers[0]["authorization"] == "Bearer k-123"
    assert out.dtype == np.float32 and out.shape == (3, 3)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-6)
    expected = np.array([_vec(t) for t in ["a", "bb", "ccc"]], dtype=np.float32)
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    np.testing.assert_allclose(out, expected, rtol=1e-6)


def test_results_without_index_keep_list_order() -> None:  # Gemini's compatible endpoint
    out = _adapter(Recorder(lambda r: _ok(r, with_index=False)), []).embed(["a", "bbbb"], "query")

    assert out[0][0] < out[1][0]


def test_rate_limit_is_retried_with_retry_after_then_backoff() -> None:
    handler = Recorder(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        _ok,
    )
    sleeps: list[float] = []

    out = _adapter(handler, sleeps).embed(["a"], "document")

    assert out.shape == (1, 3)
    assert sleeps == [7.0, 2.0]  # Retry-After, then the doubled backoff


def test_transport_errors_are_retried() -> None:
    handler = Recorder(httpx.ConnectTimeout("slow"), _ok)

    assert _adapter(handler, []).embed(["a"], "document").shape == (1, 3)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(429), ErrorCode.PROVIDER_RATE_LIMITED),
        (httpx.Response(503), ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_exhausted_retries_raise_the_matching_error(
    response: httpx.Response, code: ErrorCode
) -> None:
    sleeps: list[float] = []

    with pytest.raises(AppError) as info:
        _adapter(Recorder(response), sleeps).embed(["a"], "document")

    assert info.value.code is code
    assert len(sleeps) == 2  # 3 attempts


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.PROVIDER_AUTH),
        (403, ErrorCode.PROVIDER_AUTH),
        (404, ErrorCode.PROVIDER_UNAVAILABLE),
        (400, ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_permanent_errors_are_not_retried(status: int, code: ErrorCode) -> None:
    handler = Recorder(httpx.Response(status))

    with pytest.raises(AppError) as info:
        _adapter(handler, []).embed(["a"], "document")

    assert info.value.code is code
    assert len(handler.bodies) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"oops": 1},
        {"data": [{"embedding": [1.0, 0.0, 0.0]}]},  # one vector for two texts
        {"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]},  # wrong dimension
        {"data": [{"embedding": [0.0, 0.0, 0.0]}, {"embedding": [1.0, 0.0, 0.0]}]},  # zero vector
    ],
)
def test_malformed_responses_are_rejected(payload: dict) -> None:
    with pytest.raises(AppError) as info:
        _adapter(Recorder(httpx.Response(200, json=payload)), []).embed(["a", "b"], "document")

    assert info.value.code is ErrorCode.PROVIDER_UNAVAILABLE


def test_batches_are_throttled() -> None:
    sleeps: list[float] = []

    _adapter(Recorder(_ok), sleeps, min_seconds_between_batches=30).embed(
        ["a", "b", "c"], "document"
    )

    assert len(sleeps) == 1 and 29 < sleeps[0] <= 30


def test_extra_body_is_passed_through_and_no_dimensions_when_unset() -> None:
    handler = Recorder(_ok)

    _adapter(handler, [], dimensions=None, extra_body={"encoding_format": "float"}).embed(
        ["a"], "query"
    )

    assert handler.bodies[0] == {"model": "m", "input": ["a"], "encoding_format": "float"}


def test_empty_input_makes_no_call() -> None:
    handler = Recorder(_ok)

    assert _adapter(handler, []).embed([], "query").shape == (0, 3)
    assert handler.bodies == []


def test_build_embedder_requires_the_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMB_KEY", raising=False)
    settings = _settings(api_key_env="EMB_KEY")

    with pytest.raises(AppError) as info:
        build_embedder(settings, RetryPolicy())
    assert info.value.code is ErrorCode.PROVIDER_AUTH

    monkeypatch.setenv("EMB_KEY", "secret")
    assert build_embedder(settings, RetryPolicy()).model == "m"
    assert build_embedder(_settings(api_key_env=None), RetryPolicy()).model == "m"  # local server
