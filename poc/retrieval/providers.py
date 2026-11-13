"""Minimal embedding-provider adapters for the Phase 3 PoC.

Each adapter turns a list of texts into vectors, distinguishing document
(passage) and query inputs where the provider supports it, because retrieval
models are often trained asymmetrically.

API keys are read from environment variables and never written anywhere.
Embeddings are cached on disk by (provider, model, input type, text hash) so
re-running an experiment does not spend free-tier quota again.

Endpoints and request shapes follow each provider's public API reference; the
model IDs are parameters because free-tier model availability changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

CACHE_DIR = Path(__file__).with_name(".embedding_cache")


@dataclass
class Provider:
    name: str
    model: str
    key_env: str
    batch_size: int = 32
    pause_s: float = 1.0  # pause between batches, to stay under free-tier rate limits

    # -- to implement ------------------------------------------------------- #
    def _embed_batch(self, client: httpx.Client, texts: list[str], kind: str) -> list[list[float]]:
        raise NotImplementedError

    # -- shared ------------------------------------------------------------- #
    def available(self) -> bool:
        return bool(os.environ.get(self.key_env))

    @property
    def key(self) -> str:
        return os.environ[self.key_env]

    def embed(self, texts: list[str], kind: str) -> np.ndarray:
        """kind: 'document' or 'query'. Returns L2-normalized float32 vectors."""
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{self.name}__{self.model.replace('/', '_')}__{kind}.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        todo = [(k, t) for k, t in zip(keys, texts) if k not in cache]
        with httpx.Client(timeout=60) as client:
            for i in range(0, len(todo), self.batch_size):
                batch = todo[i:i + self.batch_size]
                vectors = self._with_retry(client, [t for _, t in batch], kind)
                for (k, _), v in zip(batch, vectors):
                    cache[k] = v
                cache_file.write_text(json.dumps(cache))
                if i + self.batch_size < len(todo):
                    time.sleep(self.pause_s)
        arr = np.array([cache[k] for k in keys], dtype=np.float32)
        return arr / np.linalg.norm(arr, axis=1, keepdims=True)

    def _with_retry(self, client: httpx.Client, texts: list[str], kind: str, attempts: int = 5):
        delay = 2.0
        for attempt in range(attempts):
            try:
                return self._embed_batch(client, texts, kind)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503) and attempt < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"{self.name}: HTTP {e.response.status_code}: {e.response.text[:300]}") from e


class Gemini(Provider):
    """Gemini API batchEmbedContents with retrieval task types."""

    def _embed_batch(self, client, texts, kind):
        task = "RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]},
                              "taskType": task} for t in texts]}
        r = client.post(url, json=body, headers={"x-goog-api-key": self.key})
        r.raise_for_status()
        return [e["values"] for e in r.json()["embeddings"]]


class Cohere(Provider):
    """Cohere v2 /embed with input_type search_document / search_query."""

    def _embed_batch(self, client, texts, kind):
        body = {"model": self.model, "texts": texts, "embedding_types": ["float"],
                "input_type": "search_document" if kind == "document" else "search_query"}
        r = client.post("https://api.cohere.com/v2/embed", json=body,
                        headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        return r.json()["embeddings"]["float"]


class Jina(Provider):
    """Jina /v1/embeddings with retrieval.passage / retrieval.query tasks."""

    def _embed_batch(self, client, texts, kind):
        body = {"model": self.model, "input": texts,
                "task": "retrieval.passage" if kind == "document" else "retrieval.query"}
        r = client.post("https://api.jina.ai/v1/embeddings", json=body,
                        headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]


class Mistral(Provider):
    """Mistral /v1/embeddings (OpenAI-compatible shape; no query/document distinction)."""

    def _embed_batch(self, client, texts, kind):
        r = client.post("https://api.mistral.ai/v1/embeddings", json={"model": self.model, "input": texts},
                        headers={"Authorization": f"Bearer {self.key}"})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]


class HashingTestDouble(Provider):
    """Deterministic local stand-in (hashed bag of words). NOT a real model:
    used only to exercise the harness end-to-end without keys."""

    def available(self) -> bool:
        return True

    def _embed_batch(self, client, texts, kind):
        import re
        out = []
        for t in texts:
            v = np.zeros(512, dtype=np.float32)
            for tok in re.findall(r"[^\W_]+", t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 512] += 1.0
            out.append((v + 1e-6).tolist())
        return out


# Candidate models (D-025). Model IDs are taken from each provider's public
# documentation and can be overridden on the command line.
CANDIDATES = {
    "gemini": lambda m=None: Gemini("gemini", m or "gemini-embedding-001", "GEMINI_API_KEY", batch_size=50, pause_s=2.0),
    "cohere": lambda m=None: Cohere("cohere", m or "embed-multilingual-v3.0", "COHERE_API_KEY", batch_size=96),
    "jina": lambda m=None: Jina("jina", m or "jina-embeddings-v3", "JINA_API_KEY", batch_size=64),
    "mistral": lambda m=None: Mistral("mistral", m or "mistral-embed", "MISTRAL_API_KEY", batch_size=32, pause_s=1.5),
    "test-double": lambda m=None: HashingTestDouble("test-double", "hashing-512", "UNUSED", pause_s=0.0),
}
