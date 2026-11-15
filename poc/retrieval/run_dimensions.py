"""Phase 6 follow-up (P-018): measure gemini-embedding-001 retrieval quality at 3072/1536/768/256 dims (MRL truncation).

Embeds once at the default 3072 dims, then truncates and L2-renormalizes locally, which is
what Google documents for output_dimensionality with this model. Also checks, with one tiny
request, whether the server's own reduced output equals local truncation.

Usage (from poc/retrieval, reuses the Phase 3 embedding cache):
  GEMINI_API_KEY=... .venv/bin/python run_dimensions.py
"""
import json
from pathlib import Path
import numpy as np
import httpx
import harness as h
from providers import CANDIDATES
from run_embeddings import auroc

docs = h.load_documents(None, "pdftotext")
chunks = h.chunk_documents(docs, 800, 150)
questions = h.load_questions(None)
p = CANDIDATES["gemini"](None)
D = p.embed([c.text for c in chunks], "document")
Q = p.embed([q.text for q in questions], "query")
print("full dims:", D.shape, "norms:", float(np.linalg.norm(D[0])), flush=True)
qi = {q.qid: i for i, q in enumerate(questions)}
rows = {}
for dim in (3072, 1536, 768, 256):
    d = D[:, :dim] / np.linalg.norm(D[:, :dim], axis=1, keepdims=True)
    qv = Q[:, :dim] / np.linalg.norm(Q[:, :dim], axis=1, keepdims=True)
    def search(text, k, d=d, qv=qv):
        qid = next(q.qid for q in questions if q.text == text)
        s = d @ qv[qi[qid]]
        top = np.argsort(-s)[:k]
        return [(chunks[i], float(s[i])) for i in top]
    r = h.evaluate(search, questions)
    pos = [v["top_score"] for v in r["per_question"].values()]
    r["auroc"] = auroc(pos, r["unanswerable_top_scores"])
    r["hit1_set"] = sorted(q for q, v in r["per_question"].items() if v.get("rank") == 1)
    rows[dim] = r
    print(f"| {dim} | {r['hit@1']:.2f} | {r['hit@3']:.2f} | {r['hit@5']:.2f} | {r['recall@5']:.2f} | {r['mrr']:.3f} | {r['auroc']:.2f} | {dim*4} B | {20000*dim*4/1e6:.0f} MB |", flush=True)

# Does the OpenAI-compatible endpoint accept `dimensions`, and is it plain truncation?
text = chunks[0].text
with httpx.Client(timeout=60) as c:
    r = c.post("https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
               json={"model": "gemini-embedding-001", "input": [text], "dimensions": 768},
               headers={"Authorization": "Bearer dummy-replaced-by-proxy"})
    print("dimensions=768 request:", r.status_code, flush=True)
    if r.status_code == 200:
        v = np.array(r.json()["data"][0]["embedding"])
        t = D[0, :768] / np.linalg.norm(D[0, :768])
        print("server len", len(v), "norm", float(np.linalg.norm(v)),
              "cosine(server, local truncation) =", float(v @ t / np.linalg.norm(v)))
    else:
        print(r.text[:300])
Path(__file__).with_name("results_dimensions.json").write_text(json.dumps({k: {x: y for x, y in v.items() if x != "per_question"} for k, v in rows.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
