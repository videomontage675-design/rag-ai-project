"""Embedding-provider comparison on the golden set (needs API keys).

For each requested provider whose key is present in the environment:
  embed all chunks (document mode) and all golden-set questions (query mode),
  rank chunks by cosine similarity, and report Hit@k / Recall@k / MRR,
  plus how well the top similarity score separates answerable from
  unanswerable questions (AUROC). Separation indicates whether a relevance
  threshold (FR-RET-06) can work for that model.

The chunking configuration is the BM25 baseline winner (pdftotext, 800/150)
so that providers are compared on identical chunks.

Usage (from poc/retrieval):
  .venv/bin/python run_embeddings.py gemini cohere jina
  .venv/bin/python run_embeddings.py cohere:embed-v4.0     # override model ID
  .venv/bin/python run_embeddings.py test-double           # pipeline check, no keys
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import harness as h
from providers import CANDIDATES


def auroc(pos: list[float], neg: list[float]) -> float:
    """Probability that a random answerable question's top score exceeds a
    random unanswerable one's (Mann-Whitney U / (n_pos * n_neg))."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def run(spec: str, chunks: list[h.Chunk], questions: list[h.Question]) -> dict | None:
    name, _, model = spec.partition(":")
    provider = CANDIDATES[name](model or None)
    if not provider.available():
        print(f"- {spec}: skipped ({provider.key_env} not set)")
        return None
    doc_vecs = provider.embed([c.text for c in chunks], "document")
    q_vecs = provider.embed([q.text for q in questions], "query")
    qindex = {q.qid: i for i, q in enumerate(questions)}

    def search(text: str, k: int):
        qid = next(q.qid for q in questions if q.text == text)
        sims = doc_vecs @ q_vecs[qindex[qid]]
        top = np.argsort(-sims)[:k]
        return [(chunks[i], float(sims[i])) for i in top]

    r = h.evaluate(search, questions)
    pos = [v["top_score"] for v in r["per_question"].values()]
    r["auroc_answerable_vs_unanswerable"] = auroc(pos, r["unanswerable_top_scores"])
    r["model"] = provider.model
    r["dimension"] = int(doc_vecs.shape[1])
    return r


def main() -> None:
    specs = sys.argv[1:] or ["gemini", "cohere", "jina"]
    docs = h.load_documents(None, "pdftotext")
    chunks = h.chunk_documents(docs, 800, 150)
    questions = h.load_questions(None)
    results = {}
    for spec in specs:
        r = run(spec, chunks, questions)
        if r:
            results[spec] = r
    if not results:
        return
    print("| Provider | Model | Dim | Hit@1 | Hit@3 | Hit@5 | Recall@5 | MRR | AUROC (threshold separability) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for spec, r in results.items():
        print(f"| {spec.split(':')[0]} | {r['model']} | {r['dimension']} | {r['hit@1']:.2f} | {r['hit@3']:.2f} | "
              f"{r['hit@5']:.2f} | {r['recall@5']:.2f} | {r['mrr']:.3f} | {r['auroc_answerable_vs_unanswerable']:.2f} |")
    out = Path(__file__).with_name("results_embeddings.json")
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    previous.update(results)
    out.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
