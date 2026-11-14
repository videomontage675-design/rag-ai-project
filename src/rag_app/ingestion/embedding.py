"""Stage 5 · Embed chunks (DESIGN-001 §8.2).

The embedded text is the chunk's heading path followed by its normalized text, so a chunk
about "2. مقارنة الخطط" carries that context into its vector (TECH-001 T-11, finding 6).
"""

from __future__ import annotations

from collections.abc import Sequence

from rag_app.domain.models import ChunkDraft
from rag_app.providers.ports import EmbeddingProvider, Vectors


def embedding_text(heading_path: str, text_normalized: str) -> str:
    """The text sent to the embedding model for one chunk."""
    return f"{heading_path}\n{text_normalized}" if heading_path else text_normalized


def embed_chunks(chunks: Sequence[ChunkDraft], embedder: EmbeddingProvider) -> Vectors:
    """Embed chunks in order; row *i* belongs to ``chunks[i]``."""
    return embedder.embed(
        [embedding_text(c.heading_path, c.text_normalized) for c in chunks], "document"
    )
