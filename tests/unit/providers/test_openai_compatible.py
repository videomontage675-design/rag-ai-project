"""The OpenAI-compatible embeddings adapter, against recorded response shapes (respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from rag_app.config.settings import ProviderSettings
from rag_app.core.errors import ErrorCode
from rag_app.domain.models import EmbeddingTask
from rag_app.providers.factory import open_embedding_provider
from rag_app.providers.openai_compatible import OpenAICompatibleEmbeddings
from rag_app.providers.ports import (
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)

pytestmark = pytest.mark.unit

BASE = "https://provider.test/v1"
URL = f"{BASE}/embeddings"
CFG = ProviderSettings(base_url=BASE, model="m-1", api_key_env="TEST_KEY", extra_body={"x": 1})


def _adapter(key: str | None = "k") -> OpenAICompatibleEmbeddings:
    return OpenAICompatibleEmbeddings(CFG, api_key=key, client=httpx.Client())


def _data(*vectors: list[float], with_index: bool = True) -> dict[str, object]:
    items = [
        {"object": "embedding", "embedding": v, **({"index": i} if with_index else {})}
        for i, v in enumerate(vectors)
    ]
    return {"object": "list", "data": items, "model": "m-1"}


@respx.mock
def test_embed_sends_model_input_extra_body_and_bearer_key() -> None:
    route = respx.post(URL).respond(200, json=_data([1.0, 0.0], [0.0, 1.0]))

    vectors = _adapter().embed(["أ", "ب"], EmbeddingTask.DOCUMENT)

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    request = route.calls.last.request
    assert json.loads(request.content) == {"x": 1, "model": "m-1", "input": ["أ", "ب"]}
    assert request.headers["authorization"] == "Bearer k"


@respx.mock
def test_embed_orders_vectors_by_index_when_present() -> None:
    body = _data([1.0, 0.0], [0.0, 1.0])
    body["data"] = list(reversed(body["data"]))  # type: ignore[call-overload]
    respx.post(URL).respond(200, json=body)

    assert _adapter().embed(["a", "b"], EmbeddingTask.QUERY) == [[1.0, 0.0], [0.0, 1.0]]


@respx.mock
def test_embed_accepts_gemini_responses_without_index() -> None:
    respx.post(URL).respond(200, json=_data([1.0, 2.0], [3.0, 4.0], with_index=False))

    assert _adapter().embed(["a", "b"], EmbeddingTask.DOCUMENT) == [[1.0, 2.0], [3.0, 4.0]]


def test_embed_of_nothing_makes_no_request() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL)
        assert _adapter().embed([], EmbeddingTask.DOCUMENT) == []
    assert not route.called


def test_missing_key_fails_before_any_request_and_names_the_variable() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL)
        with pytest.raises(ProviderAuthError) as info:
            _adapter(key=None).embed(["a"], EmbeddingTask.DOCUMENT)
    assert not route.called
    assert "TEST_KEY" in info.value.reason
    assert info.value.retryable is False


@respx.mock
def test_local_provider_without_key_sends_no_authorization_header() -> None:
    cfg = ProviderSettings(base_url="http://127.0.0.1:11434/v1", model="local")
    route = respx.post("http://127.0.0.1:11434/v1/embeddings").respond(200, json=_data([1.0]))

    OpenAICompatibleEmbeddings(cfg, api_key=None, client=httpx.Client()).embed(
        ["a"], EmbeddingTask.DOCUMENT
    )

    assert "authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize(
    ("status", "body", "error", "retryable"),
    [
        (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, ProviderRateLimitedError, True),
        (500, {}, ProviderUnavailableError, True),
        (503, [{"error": {"status": "UNAVAILABLE"}}], ProviderUnavailableError, True),
        (408, {}, ProviderUnavailableError, True),
        (404, {"error": {"status": "NOT_FOUND"}}, ProviderUnavailableError, False),
        (401, {"error": {"type": "invalid_api_key"}}, ProviderAuthError, False),
        (403, {}, ProviderAuthError, False),
        (
            400,
            [{"error": {"message": "API key not valid. Please pass a valid API key."}}],
            ProviderAuthError,
            False,
        ),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, ProviderBadResponseError, False),
        (422, {}, ProviderBadResponseError, False),
    ],
)
@respx.mock
def test_http_errors_map_to_typed_provider_errors(
    status: int, body: object, error: type[ProviderError], retryable: bool
) -> None:
    respx.post(URL).respond(status, json=body)

    with pytest.raises(error) as info:
        _adapter().embed(["a"], EmbeddingTask.DOCUMENT)

    assert info.value.retryable is retryable
    assert info.value.status == status
    assert str(status) in info.value.reason


@respx.mock
def test_error_reason_keeps_the_error_type_but_never_the_message() -> None:
    respx.post(URL).respond(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "سر"}})

    with pytest.raises(ProviderBadResponseError) as info:
        _adapter().embed(["نص المستند"], EmbeddingTask.DOCUMENT)

    assert info.value.reason == "HTTP 400 INVALID_ARGUMENT"
    assert info.value.code is ErrorCode.PROVIDER_BAD_RESPONSE


@pytest.mark.parametrize(("header", "expected"), [("12", 12.0), ("1.5", 1.5), ("soon", None)])
@respx.mock
def test_rate_limit_reads_retry_after_seconds(header: str, expected: float | None) -> None:
    respx.post(URL).respond(429, headers={"Retry-After": header})

    with pytest.raises(ProviderRateLimitedError) as info:
        _adapter().embed(["a"], EmbeddingTask.DOCUMENT)

    assert info.value.retry_after == expected


@pytest.mark.parametrize("exception", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
@respx.mock
def test_timeouts_and_network_failures_are_retryable_unavailability(
    exception: Exception,
) -> None:
    respx.post(URL).mock(side_effect=exception)

    with pytest.raises(ProviderUnavailableError) as info:
        _adapter().embed(["a"], EmbeddingTask.DOCUMENT)

    assert info.value.retryable is True


@pytest.mark.parametrize(
    ("body", "texts"),
    [
        ("not json", ["a"]),
        ({"nodata": []}, ["a"]),
        (_data([1.0]), ["a", "b"]),  # too few vectors
        (_data([1.0], [2.0], [3.0]), ["a", "b"]),  # too many
        ({"data": [[1.0]]}, ["a"]),  # items are not objects
        ({"data": [{"embedding": [1.0], "index": 5}]}, ["a"]),  # index out of range
        ({"data": [{"embedding": []}]}, ["a"]),
        ({"data": [{"embedding": "1,2"}]}, ["a"]),
        ({"data": [{"embedding": [True, False]}]}, ["a"]),
        ({"data": [{"embedding": [1.0, "x"]}]}, ["a"]),
        (_data([1.0, 2.0], [1.0]), ["a", "b"]),  # different lengths
    ],
)
@respx.mock
def test_malformed_responses_are_rejected(body: object, texts: list[str]) -> None:
    if isinstance(body, str):
        respx.post(URL).respond(200, text=body)
    else:
        respx.post(URL).respond(200, json=body)

    with pytest.raises(ProviderBadResponseError):
        _adapter().embed(texts, EmbeddingTask.DOCUMENT)


@respx.mock
def test_non_finite_values_are_rejected() -> None:
    respx.post(URL).respond(
        200, content=b'{"data": [{"embedding": [1.0, NaN]}]}', headers={"content-type": "x"}
    )

    with pytest.raises(ProviderBadResponseError):
        _adapter().embed(["a"], EmbeddingTask.DOCUMENT)


def test_factory_reads_the_key_from_the_named_variable_only() -> None:
    with_key = open_embedding_provider(CFG, env={"TEST_KEY": "secret", "OTHER": "x"})
    without_key = open_embedding_provider(CFG, env={"TEST_KEY": ""})

    assert with_key._api_key == "secret"
    assert without_key._api_key is None
    assert with_key.model == "m-1"
    with_key.close()
    without_key.close()
