"""Stage 5 (embedding) as a function: inputs, batching, validation, normalization."""

from __future__ import annotations

import numpy as np
import pytest

from fakes.embeddings import FakeEmbeddingProvider
from rag_app.domain.models import EmbeddingTask
from rag_app.ingestion.embedding import embed_texts, embedding_text, normalized
from rag_app.providers.ports import ProviderBadResponseError

pytestmark = pytest.mark.unit


class ScriptedProvider:
    """Returns the given vectors per call, whatever the input."""

    model = "scripted"

    def __init__(self, *responses: list[list[float]]) -> None:
        self._responses = list(responses)

    def embed(self, texts: object, task: EmbeddingTask) -> list[list[float]]:
        return self._responses.pop(0)


def test_embedding_text_prefixes_the_normalized_heading_path() -> None:
    text = embedding_text("الإصدار ٤ › التغييرات المُهمّة", "نص المقطع")

    assert text == "الإصدار 4 › التغييرات المهمة\nنص المقطع"


def test_embedding_text_without_heading_is_the_chunk_text() -> None:
    assert embedding_text("  ", "نص") == "نص"


def test_embed_texts_batches_in_order_and_reports_progress() -> None:
    provider = FakeEmbeddingProvider()
    progress: list[tuple[int, int]] = []
    texts = [f"نص {i}" for i in range(5)]

    vectors = embed_texts(
        texts, provider, batch_size=2, on_batch=lambda d, t: progress.append((d, t))
    )

    assert [call[0] for call in provider.calls] == [
        tuple(texts[0:2]),
        tuple(texts[2:4]),
        (texts[4],),
    ]
    assert {call[1] for call in provider.calls} == {EmbeddingTask.DOCUMENT}
    assert progress == [(0, 5), (2, 5), (4, 5)]
    assert (vectors.model, vectors.dim, len(vectors)) == ("fake-embedding", 32, 5)
    expected = np.asarray(provider.vector("نص 3"))
    assert np.allclose(vectors.matrix[3], expected / np.linalg.norm(expected))


def test_vectors_are_unit_length_float32_and_read_only() -> None:
    vectors = embed_texts(["أ", "ب ت"], FakeEmbeddingProvider(), batch_size=10)

    assert vectors.matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors.matrix, axis=1), 1.0, atol=1e-6)
    with pytest.raises(ValueError, match="read-only"):
        vectors.matrix[0, 0] = 5.0


def test_cancellation_raised_from_progress_stops_before_the_next_batch() -> None:
    provider = FakeEmbeddingProvider()

    def cancel(done: int, _total: int) -> None:
        if done >= 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        embed_texts(["a", "b", "c"], provider, batch_size=2, on_batch=cancel)

    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "responses",
    [
        ([[1.0, 0.0]],),  # one vector for two texts
        ([[1.0, 0.0], [1.0]],),  # ragged batch
        ([[1.0, 0.0], [0.0, 0.0]],),  # zero vector
        ([[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0, 0.0]]),  # dimension changes between batches
        ([[], []],),  # empty vectors
    ],
)
def test_unusable_provider_output_is_rejected(responses: tuple[list[list[float]], ...]) -> None:
    texts = ["a", "b"] + (["c"] if len(responses) > 1 else [])

    with pytest.raises(ProviderBadResponseError):
        embed_texts(texts, ScriptedProvider(*responses), batch_size=2)


@pytest.mark.parametrize(("texts", "batch_size"), [([], 2), (["a"], 0)])
def test_invalid_arguments_are_programming_errors(texts: list[str], batch_size: int) -> None:
    with pytest.raises(ValueError):
        embed_texts(texts, FakeEmbeddingProvider(), batch_size=batch_size)


def test_normalized_rejects_non_finite_rows() -> None:
    with pytest.raises(ProviderBadResponseError):
        normalized("m", np.array([[np.inf, 1.0]]))
