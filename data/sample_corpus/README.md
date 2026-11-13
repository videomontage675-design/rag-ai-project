# Dafira sample corpus

> **Fictional content.** "ضفيرة" (Dafira) is an invented cloud platform for managing medical clinics.
> All companies, prices, policies, dates, and figures in these documents are fictional. They were
> written for testing a RAG system and must not be read as real product, legal, or medical information.

| Path | Content |
|---|---|
| `source/` | Reference Markdown text of every document version (authored first; ground truth) |
| `pdf/` | PDFs rendered from the corresponding sources (uploaded as PDF) |
| `reference_text/` | Plain text rendered from each PDF's HTML, used to measure extraction quality |
| `manifest.yaml` | Documents, versions, upload files, corpus states, ingestion sequence |
| `facts.yaml` | Registry of cross-document facts, checked automatically for consistency |
| `verification_report.json` | Latest output of `tools/corpus/verify_corpus.py` |

The golden set is in `eval/golden_set.yaml`. Design, rationale, and verification results are in
`docs/02_SAMPLE_CORPUS.md`.
