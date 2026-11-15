"""A deterministic stand-in for the embedding provider (NFR-MNT-02: no real calls in tests).

Character trigrams are hashed into a fixed-size vector, so similar texts get similar vectors
and the same text always gets the same vector.
"""

from __future__ import annotations

import hashlib

import numpy as np

from rag_app.core.errors import AppError, ErrorCode
from rag_app.providers.ports import EmbeddingTask, Vectors


class FakeEmbedder:
    """Implements ``EmbeddingProvider``; records calls; can be told to fail."""

    def __init__(self, model: str = "fake-embedding", dimensions: int = 32) -> None:
        self._model = model
        self._dimensions = dimensions
        self.calls: list[tuple[int, EmbeddingTask]] = []
        self.fail_with: ErrorCode | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def embed(self, texts: list[str], task: EmbeddingTask) -> Vectors:
        self.calls.append((len(texts), task))
        if self.fail_with is not None:
            raise AppError(self.fail_with)
        out = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for i in range(max(1, len(text) - 2)):
                digest = hashlib.blake2b(text[i : i + 3].encode(), digest_size=4).digest()
                out[row, int.from_bytes(digest, "little") % self._dimensions] += 1.0
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
        return out
