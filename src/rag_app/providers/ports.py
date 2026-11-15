"""Provider ports: what the pipeline needs from a model, whatever the vendor (D-010, D-013)."""

from __future__ import annotations

from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

EmbeddingTask = Literal["document", "query"]
Vectors = npt.NDArray[np.float32]


class EmbeddingProvider(Protocol):
    """Turns texts into L2-normalized float32 vectors (one row per text, same order)."""

    @property
    def model(self) -> str:
        """Model identifier stored with every vector (FR-ING-12)."""
        ...

    @property
    def dimensions(self) -> int | None:
        """Requested vector size, or ``None`` for the model's default size."""
        ...

    def embed(self, texts: list[str], task: EmbeddingTask) -> Vectors:
        """Embed ``texts``. Raises ``AppError`` with a ``PROVIDER_*`` code on failure."""
        ...
