"""Opt-in check against the real embedding provider (NFR-MNT-02: never part of the normal run).

Run with (PowerShell: set the variable first):
    RAG_PROVIDER_TESTS=1 uv run pytest -m provider --allow-hosts=<provider host>
It needs the configured key in the environment and sends two short fictional sentences.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from dotenv import load_dotenv

from rag_app.config.settings import load_settings
from rag_app.providers.openai_compatible import RetryPolicy, build_embedder

pytestmark = [
    pytest.mark.provider,
    pytest.mark.skipif(os.environ.get("RAG_PROVIDER_TESTS") != "1", reason="opt-in only"),
]
ROOT = Path(__file__).resolve().parents[2]


def test_configured_embedding_provider_returns_normalized_vectors_of_the_configured_size() -> None:
    load_dotenv(ROOT / ".env")
    config = load_settings(ROOT / "config" / "settings.toml").providers.embedding
    embedder = build_embedder(config, RetryPolicy(max_attempts=3, first_backoff_seconds=5))

    vectors = embedder.embed(
        ["كم سعر الخطة الأساسية؟", "سعر الخطة الأساسية 59 دولاراً شهرياً."], "document"
    )

    assert vectors.shape == (2, config.dimensions or vectors.shape[1])
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)
    assert float(vectors[0] @ vectors[1]) > 0.5  # a question and its answer are close
