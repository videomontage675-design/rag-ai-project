"""Builds provider adapters from settings; called only by composition roots (STD-001 §4)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from rag_app.config.settings import ProviderSettings
from rag_app.providers.openai_compatible import OpenAICompatibleEmbeddings


def open_embedding_provider(
    cfg: ProviderSettings, env: Mapping[str, str] | None = None
) -> OpenAICompatibleEmbeddings:
    """Create the embedding adapter, reading its key from ``env`` (default: the process).

    A missing key is not an error here: the app must still start so the owner can manage
    documents, and ``rag check`` reports the missing variable. The first call fails with
    ``PROVIDER_AUTH`` instead.
    """
    environment = os.environ if env is None else env
    api_key = environment.get(cfg.api_key_env) if cfg.api_key_env else None
    return OpenAICompatibleEmbeddings(cfg, api_key=api_key or None)
