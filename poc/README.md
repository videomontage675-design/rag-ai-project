# Phase 3 proofs of concept

Throwaway measurement code for the technology evaluation (Phase 3). These
scripts are not part of the application. Their results feed
`docs/03_TECHNOLOGY_EVALUATION.md`.

| Folder | Question answered |
|---|---|
| `extraction/` | Which PDF text extractor handles the Arabic sample PDFs best? |
| `retrieval/` | How do extractor, normalization, chunking, BM25, and embedding providers affect retrieval on the golden set? (`run_lexical.py` needs no keys; `run_embeddings.py` needs provider keys.) |

Each folder has a pinned `requirements.txt` and its own virtual environment (`.venv`, not committed).
