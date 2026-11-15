"""Stage 5: embed chunks through the provider port (DESIGN-001 §8.2, FR-ING-11/12).

This module decides *what* is embedded and checks *what comes back*; the provider adapter
decides how to reach the model, and its wrappers handle retries and throttling.

* The embedded text is the **normalized heading path + normalized chunk text**, so a chunk
  carries the section it belongs to (Phase 3, T-11 finding 6). The same function serves
  ingestion and re-indexing, so both always embed identical inputs.
* Vectors are L2-normalized float32, so a dot product is the cosine similarity (T-05).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from rag_app.domain.models import EmbeddingTask, VectorSet
from rag_app.ingestion.normalization import normalize_arabic
from rag_app.providers.ports import EmbeddingProvider, ProviderBadResponseError


def embedding_text(heading_path: str, text_normalized: str) -> str:
    """The text sent to the embedding model for one chunk."""
    heading = normalize_arabic(heading_path).strip()
    return f"{heading}\n{text_normalized}" if heading else text_normalized


def embed_texts(
    texts: Sequence[str],
    provider: EmbeddingProvider,
    *,
    batch_size: int,
    task: EmbeddingTask = EmbeddingTask.DOCUMENT,
    on_batch: Callable[[int, int], None] = lambda _done, _total: None,
) -> VectorSet:
    """Embed ``texts`` in batches and return one normalized vector per text, in order.

    ``on_batch(done, total)`` is called before each batch, so the caller can show progress
    and stop a cancelled job between batches (DD-02) by raising from the callback.

    Raises:
        ProviderError: from the provider, or ``ProviderBadResponseError`` when a batch returns the
            wrong number of vectors, mixed dimensions, or a zero vector.
        ValueError: when ``texts`` is empty or ``batch_size`` is not positive.
    """
    if not texts:
        msg = "nothing to embed"
        raise ValueError(msg)
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)
    parts: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        on_batch(start, len(texts))
        batch = texts[start : start + batch_size]
        vectors = provider.embed(batch, task)
        if len(vectors) != len(batch):
            msg = f"expected {len(batch)} vectors, got {len(vectors)}"
            raise ProviderBadResponseError(msg)
        try:
            parts.append(np.asarray(vectors, dtype=np.float64).reshape(len(batch), -1))
        except ValueError as exc:  # ragged rows cannot form a matrix
            msg = "vectors in one batch have different lengths"
            raise ProviderBadResponseError(msg) from exc
    if len({part.shape[1] for part in parts}) != 1:
        msg = "batches returned different dimensions"
        raise ProviderBadResponseError(msg)
    return normalized(provider.model, np.vstack(parts))


def normalized(model: str, matrix: np.ndarray) -> VectorSet:
    """Return ``matrix`` as a read-only :class:`VectorSet` with unit-length float32 rows.

    Raises:
        ProviderBadResponseError: a row is all zeros, so it has no direction to compare.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if matrix.shape[1] == 0 or not np.all(np.isfinite(norms)) or not np.all(norms > 0):
        msg = "zero or malformed vector"
        raise ProviderBadResponseError(msg)
    unit = (matrix / norms).astype(np.float32)
    unit.setflags(write=False)
    return VectorSet(model=model, dim=int(unit.shape[1]), matrix=unit)
