# Changelog

All notable changes, one section per phase. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (`0.y.z` until delivery).

## [0.3.0] — Phase 7: Embeddings, indexing, and re-indexing

### Added
- **Provider layer** (`providers/`):
  - the `EmbeddingProvider` port with typed errors (`retryable` flag);
  - one OpenAI-compatible adapter (Gemini by default) that validates every response;
  - throttling between requests and exponential backoff that honours `Retry-After`.
- **Stage 5 (embed)** in the ingestion worker:
  - the normalized heading path and chunk text are embedded in batches;
  - vectors are L2-normalized float32, stored with model and dimension in the same transaction as the chunks (FR-ING-11/12/13);
  - cancellation is checked before every batch;
  - provider waits end at once on shutdown.
- **One model at a time:** vectors of a second model are refused (`REINDEX_REQUIRED`) before any quota is spent.
- **`VectorIndex`:** the active vectors in a read-only NumPy matrix, reloaded only when the index generation changes (D-039). Search comes in Phase 8.
- **`rag reindex`:** embeds what lacks a vector of the configured model into a staging table, then swaps everything in with one transaction. It resumes after interruption and prints its plan first (FR-CFG-05).
- **Checks:**
  - `rag check` reports vector-index consistency and when a re-index is needed;
  - `/api/v1/system/status` adds `versions_missing_vectors`;
  - version details show the embedding model.
- **Errors:** `PROVIDER_BAD_RESPONSE`.
- **Database:** migration `0003` (re-index staging, index on the vector model).
- **Settings:** `[ingestion] provider_retry_attempts` and `provider_retry_initial_seconds`.
- **Dependencies:** NumPy and httpx at runtime; respx for tests.
- **Tests:** 312 passing, 1 known gap as a strict expected failure. No test reaches a provider. Covered:
  - adapter behaviour against recorded response shapes;
  - retries and throttling with a fake clock;
  - failure, cancellation, and model-mismatch paths;
  - re-index resume and concurrency;
  - the configured app end to end with mocked HTTP;
  - the whole sample corpus.

### Upgrading from 0.2.0
Documents processed by 0.2.0 have chunks but no vectors. Stop the app and run `uv run rag reindex` once; `rag check` warns until you do.

### Known limitations
- No real call to the embedding provider has been made in this phase (D-039); all provider behaviour is tested against mocked HTTP.
- Questions cannot be asked yet (Phases 8–10).

## [0.2.0] — Phase 6: Document ingestion and the documents interface

### Added
- **Ingestion stages 1–4** (`ingestion/`, pure functions):
  - validation by content rather than file name;
  - Markdown structure (headings, lists, table rows);
  - PDF extraction with Poppler, with timeouts and specific errors for scanned, encrypted, and damaged files;
  - clean-up rules measured on the corpus;
  - Arabic normalization for search;
  - structure-aware chunking with full heading paths.
- **Storage:**
  - `FileStore` (streamed uploads with a size limit and SHA-256, generated names, orphan sweep);
  - `DocumentRepository` (one transaction per use case, the one-commit ingestion rule, cancellation, crash recovery);
  - migration `0002` so version numbers are never reused.
- **Services:**
  - `DocumentService` (upload, new version, approve, retry, delete);
  - `IngestionWorker` (a background thread that wakes on upload and recovers interrupted jobs).
- **JSON API:** the document and version endpoints of DESIGN-001 §11.1. Oversized uploads are refused before the body is read.
- **Interface and identity (D-034, UI-001):**
  - the Dafira braid mark;
  - self-hosted Arabic fonts and vendored htmx;
  - the document library with drag-and-drop upload and live status;
  - document details with a version timeline;
  - accessible confirmation dialogs and Arabic alerts;
  - a redesigned home page;
  - a mobile layout.
- **Security:** the local-only guard (refuses foreign hosts and cross-site changes) and security headers, including a strict Content-Security-Policy (D-035).
- **Tests:** unit, integration, API, and UI tests (218 passing, 1 known gap as a strict expected failure), plus the NFR-LNG-02 corpus acceptance test on Linux and Windows. Failure-path PDFs are built in code.
- **Docs:** `docs/07_UI_AND_IDENTITY.md`; DESIGN-001 §19 implementation notes; an updated README and developer guide.

### Known limitations
- Versions are chunked but not embedded yet (Phase 7), so they are not searchable and questions cannot be asked yet.
- One golden-set evidence passage in `02_plans_pricing_v1.pdf` is split by a wrapped table cell; accepted as a known limitation (D-037).

## [0.1.0] — Phase 5: Project foundation

### Added
- **Project and tooling:** a uv project with a universal lockfile; ruff (including UTF-8 file I/O enforcement); mypy in strict mode; import-linter with five architecture contracts; pytest with the network blocked.
- **Foundation packages:**
  - an error catalog with stable codes and Arabic messages;
  - structured JSON logging with request IDs;
  - typed, validated settings that only allow loopback hosts;
  - the domain profile for the Dafira assistant.
- **Storage:**
  - SQLite in WAL mode with foreign keys and explicit transactions;
  - atomic, forward-only migrations;
  - the initial schema, with an index for every hot query and the `active_chunk_vectors` view.
- **Web:**
  - a FastAPI app factory;
  - the JSON error contract;
  - `X-Request-ID` on every response;
  - `GET /health` and `GET /api/v1/system/status`;
  - an Arabic right-to-left welcome page.
- **CLI:** `rag check` (domain profile, data folder, database, Poppler, keys) and `rag serve`.
- **CI:** GitHub Actions on Ubuntu and Windows (Python 3.13), plus Ubuntu with Python 3.12; Poppler from conda-forge; Mermaid diagram validation.
- **Documentation:** a README with a Windows quick start and a data-flow disclosure; the developer guide (`docs/06_DEVELOPER_GUIDE.md`); this changelog.

### Earlier phases (documentation only)
- Phase 0–1: plan and requirements (`docs/01_SRS.md`).
- Phase 2: Arabic sample corpus and golden set.
- Phase 3: technology evaluation.
- Phase 4: architecture and design.
- Phase 5, before any code: engineering standards (`docs/05_ENGINEERING_STANDARDS.md`).
