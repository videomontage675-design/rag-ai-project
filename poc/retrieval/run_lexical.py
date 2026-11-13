"""Lexical (BM25) baseline experiments. Needs no API keys.

Varies one factor at a time against a fixed baseline, so each effect is
attributable:
  - PDF extractor (pdftotext vs pypdfium2)
  - Arabic normalization (basic vs + alef/yaa/taa unification)
  - light prefix stemming (ال، وال، بال، ...)
  - chunk size

Also reports "evidence coverage": how many golden-set evidence entries can be
satisfied by at least one chunk at all. Lost coverage means extraction or
chunking broke the evidence text, which no retriever can recover from.

Usage (from poc/retrieval):  .venv/bin/python run_lexical.py
"""

from __future__ import annotations

import json
from pathlib import Path

import harness as h

BASE = {"extractor": "pdftotext", "norm": "basic", "stem": False, "size": 800, "overlap": 150}
NORMS = {
    "basic": h.Normalization(),                                  # NFKC + tashkeel + digits
    "full": h.Normalization(alef=True, yaa_taa=True),            # + alef / yaa / taa marbuta
}

VARIANTS = [
    BASE,
    {**BASE, "extractor": "pypdfium2"},
    {**BASE, "norm": "full"},
    {**BASE, "norm": "full", "stem": True},
    {**BASE, "size": 500, "overlap": 100},
    {**BASE, "size": 1200, "overlap": 200},
]


def label(v: dict) -> str:
    return f"{v['extractor']} | norm={v['norm']} | stem={'on' if v['stem'] else 'off'} | chunk={v['size']}/{v['overlap']}"


def main() -> None:
    questions = h.load_questions(None)
    total_ev = sum(len(q.evidence) for q in questions)
    rows, results = [], {}
    for v in VARIANTS:
        docs = h.load_documents(None, v["extractor"])
        chunks = h.chunk_documents(docs, v["size"], v["overlap"])
        missing = h.coverage_report(chunks, questions)
        bm25 = h.BM25(chunks, NORMS[v["norm"]], v["stem"])
        r = h.evaluate(bm25.search, questions)
        r.update({"chunks": len(chunks), "evidence_missing": missing})
        results[label(v)] = r
        rows.append(f"| {label(v)} | {len(chunks)} | {total_ev - len(missing)}/{total_ev} | "
                    f"{r['hit@1']:.2f} | {r['hit@3']:.2f} | {r['hit@5']:.2f} | {r['recall@5']:.2f} | {r['mrr']:.3f} |")

    print("| Configuration (BM25) | Chunks | Evidence coverable | Hit@1 | Hit@3 | Hit@5 | Recall@5 | MRR |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    for name, r in results.items():
        if r["evidence_missing"]:
            print(f"\n{name}: evidence not coverable -> {r['evidence_missing']}")

    out = Path(__file__).with_name("results_lexical.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
