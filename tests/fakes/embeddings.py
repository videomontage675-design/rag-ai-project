"""A fake embedding provider: deterministic vectors, call recording, scripted failures."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from rag_app.domain.models import EmbeddingTask

_TOKEN = re.compile(r"[^\W_]+")


@dataclass
class FakeEmbeddingProvider:
    """Hashed bag of words: texts that share words get similar vectors. NOT a real model.

    ``failures`` are raised one per call, in order, before any vector is returned; ``None``
    in the list means "succeed on this call".
    """

    model: str = "fake-embedding"
    dim: int = 32
    failures: list[Exception | None] = field(default_factory=list)
    calls: list[tuple[tuple[str, ...], EmbeddingTask]] = field(default_factory=list)

    def embed(self, texts: Sequence[str], task: EmbeddingTask) -> list[list[float]]:
        self.calls.append((tuple(texts), task))
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return [self.vector(t) for t in texts]

    def vector(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        for token in _TOKEN.findall(text) or [text]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            values[digest[0] % self.dim] += 1.0
        values[-1] += 0.5  # never a zero vector, even for text without words
        return values

    @property
    def texts_embedded(self) -> int:
        return sum(len(texts) for texts, _ in self.calls)
