# Developer Guide

| Item | Value |
|---|---|
| Document ID | DEV-001 |
| For | Anyone who will read, change, or maintain this code, now or years from now |
| After reading | You can find any piece of the system, follow a request through it, add a feature in the right place, and know which document to update |
| Status | Phase 5 (foundation). Updated with every phase |
| Rules | Binding standards are in [`05_ENGINEERING_STANDARDS.md`](05_ENGINEERING_STANDARDS.md) (STD-001); this guide explains and points to them |

---

## 1. The System in One Picture

```mermaid
flowchart LR
    browser(["🖥️ Browser<br/>Arabic RTL pages"]) --> web
    cli(["⌨️ rag CLI<br/>check · serve · reindex"]) --> services
    subgraph app["⚙️ rag_app (one Python process, 127.0.0.1)"]
        web["🖥️ web<br/>HTTP ⇄ service calls"] --> services["⚙️ services<br/>use cases"]
        services --> pipeline{{"🔶 pipeline<br/>ingestion · retrieval · generation"}}
        services --> storage[("🗄️ storage<br/>SQLite · SQL lives here only")]
        pipeline --> providers>"☁️ providers<br/>embeddings · chat"]
    end
    storage --> dbfile[("🗄️ app_data/rag.db")]
    providers --> cloud>"☁️ Gemini · Groq"]

    classDef person fill:#E8F0FE,stroke:#1A73E8,color:#202124
    classDef service fill:#E6F4EA,stroke:#188038,color:#202124
    classDef stage fill:#FEF7E0,stroke:#B06000,color:#202124
    classDef store fill:#F3E8FD,stroke:#8430CE,color:#202124
    classDef external fill:#FCE8E6,stroke:#C5221F,color:#202124
    class browser,cli,web person
    class services service
    class pipeline stage
    class storage,dbfile store
    class providers,cloud external
```

**The one rule behind the picture:** each box talks only to the boxes below it.
- The web layer never runs SQL; it asks a service.
- The pipeline never knows which provider or database is used; it receives interfaces.

This is what lets a failure stay inside one box and lets a box be replaced without touching the others. The rule is **checked automatically** by `uv run lint-imports` (§4).

---

## 2. Project Structure

```text
rag-ai-project/
├── src/rag_app/                    the application (one package)
│   ├── cli.py                      ⌨️ rag check | rag serve | rag reindex
│   ├── web/                        🖥️ interface: HTTP only, no business rules, no SQL
│   │   ├── app.py                     composition root: builds and wires every dependency
│   │   ├── context.py                 AppContext handed to request handlers
│   │   ├── middleware.py              X-Request-ID · upload size guard · local-only guard + security headers
│   │   ├── errors.py                  every error → one JSON shape (or an Arabic alert for HTMX)
│   │   ├── api/                       JSON API under /api/v1: system.py · documents.py · schemas.py
│   │   ├── ui/                        pages.py (pages + HTMX fragments) · format.py (Arabic labels, dates)
│   │   ├── templates/                 base.html · index.html · documents/ · partials/
│   │   └── static/                    app.css · app.js · brand/ · fonts/ · vendor/htmx (UI-001)
│   ├── services/                   ⚙️ use cases: the only entry point for web and CLI
│   │   ├── documents.py               DocumentService: upload, versions, activate, retry, delete
│   │   ├── ingestion_worker.py        IngestionWorker: background thread, recovery, cancellation
│   │   ├── reindex.py                 ReindexService: embed what is missing, swap in one step
│   │   ├── system.py                  knowledge-base status
│   │   └── diagnostics.py             checks behind `rag check` (incl. vector-index consistency)
│   ├── ingestion/                  🔶 stages 1–5 (no SQL; providers only through the port)
│   │   ├── validation.py              type by content, UTF-8, display name
│   │   ├── extract_pdf.py · poppler.py   pdfinfo/pdftotext with timeouts (D-028)
│   │   ├── extract_markdown.py        headings, lists, table rows (markdown-it-py)
│   │   ├── cleaning.py                PDF clean-up rules measured on the corpus
│   │   ├── normalization.py           text used for search (NFKC, tashkeel, digits)
│   │   ├── chunking.py                structure-aware chunks with full heading paths
│   │   ├── pipeline.py                process_file(): stages 2–4 in order
│   │   └── embedding.py               stage 5: embedded text, batches, checks, L2 normalization
│   ├── retrieval/ generation/      🔶 RAG pipeline stages (Phases 8–9)
│   │   evaluation/
│   ├── storage/                    🗄️ the only place with SQL and the uploads folder
│   │   ├── db.py                      connections, pragmas, transactions
│   │   ├── migrate.py                 applies numbered migrations atomically
│   │   ├── migrations/                0001 schema + indexes + view · 0002 version counter · 0003 re-index staging
│   │   ├── files.py                   FileStore: streamed uploads, generated names, orphan sweep
│   │   ├── vectors.py                 vector byte format (float32 LE) and index metadata (meta)
│   │   ├── vector_index.py            VectorIndex: active vectors in memory, reloaded on change
│   │   └── repositories/              system.py · documents.py (documents, versions, chunks, vectors, jobs) · index.py (re-index, consistency)
│   ├── providers/                  ☁️ model providers behind interfaces
│   │   ├── ports.py                   EmbeddingProvider Protocol + typed ProviderError classes
│   │   ├── openai_compatible.py       one adapter for Gemini, Cohere, or a local server (T-13)
│   │   ├── resilience.py              retries with backoff, throttling between requests
│   │   └── factory.py                 builds the adapter from settings (key read from the environment)
│   ├── config/                     🧩 typed settings and domain profile loaders
│   ├── core/                       🧩 errors (catalog), logging, ids, clock
│   └── domain/                     🧩 shared vocabulary: statuses, formats, outcomes
├── tests/  unit/ integration/      mirrors src/; network blocked by default; support/ = shared helpers; fakes/ = provider fakes
├── config/ settings.toml domain_profile.toml
├── docs/                           all project documents (§7)
├── data/sample_corpus/ eval/       Phase 2 corpus and golden set (read-only for tests)
├── poc/ tools/                     measurement tools; tools/brand/make_braid.py draws the logo
├── .github/workflows/ci.yml        CI on Linux and Windows
└── pyproject.toml uv.lock          dependencies (locked) and tool configuration
```

**Where does new code go?** Ask what it *is*:

| It… | Put it in |
|---|---|
| …turns HTTP into a call and back | `web/api/` (JSON) or `web/ui/` (pages) |
| …is a user-level action (upload, ask, delete) | `services/` |
| …transforms data for one RAG step, with no I/O | the pipeline package of that step |
| …reads or writes the database | `storage/repositories/` |
| …talks to a model provider | `providers/` |
| …is a closed set of values used across layers | `domain/models.py` |
| …is a new user-facing error | `core/errors.py` (code + Arabic message + test) |

---

## 3. How a Request Flows

```mermaid
sequenceDiagram
    autonumber
    actor U as 👤 User / client
    participant M as 🖥️ middleware
    participant R as 🖥️ router (web/api)
    participant S as ⚙️ service
    participant Q as 🗄️ repository
    participant D as 🗄️ SQLite

    U->>M: GET /api/v1/system/status
    M->>M: assign X-Request-ID (all logs of this request carry it)
    M->>R: forward
    R->>S: get_system_status(settings, db)
    S->>Q: read_snapshot(db)
    Q->>D: SELECT … (one consistent read)
    D-->>Q: rows
    Q-->>S: StorageSnapshot (plain dataclass)
    S-->>R: SystemStatus (plain dataclass)
    R-->>M: Pydantic response model → JSON
    M-->>U: 200 + X-Request-ID
    Note over M,R: Any AppError raised anywhere becomes<br/>{"error": {code, message, details}} with its HTTP status
```

Plain dataclasses cross the layers. Pydantic models exist only at the edges: API responses (`web/api/schemas.py`) and settings (`config/`). Changing the API format therefore never ripples into the pipeline.

---

## 4. Architecture Rules and How They Are Enforced

| Rule | Checked by |
|---|---|
| Layers import downwards only (`web`/`cli` → `services` → pipeline → `storage`/`providers` → `domain`/`config`/`core`) | `lint-imports` (contract 1) |
| Only `web` imports FastAPI, Jinja2, or Starlette | `lint-imports` (contract 2) |
| Only `storage` imports `sqlite3` | `lint-imports` (contract 3) |
| Only `providers` imports `httpx` | `lint-imports` (contract 4) |
| `web` and `cli` never import a repository (the UI is isolated from the database) | `lint-imports` (contract 5) |
| Full type annotations; strict typing | `mypy` |
| UTF-8 file I/O, pathlib, no blind `except`, docstrings | `ruff` |
| Tests never use the network | `pytest-socket` |

CI runs all of these on **Linux and Windows** for every push. A red check blocks merging.

---

## 5. How the API Works

### 5.1 Conventions
| Topic | Convention |
|---|---|
| Base path | `/api/v1`. A breaking change would get `/api/v2`, with v1 kept until clients move |
| Format | JSON in, JSON out, UTF-8. Arabic is returned as-is (not escaped) |
| Errors | Always `{"error": {"code": "FILE_TOO_LARGE", "message": "<Arabic>", "details": {}}}`. The `code` is stable and meant for programs; the `message` is for people |
| Status codes | Taken from the error catalog (`core/errors.py`). Examples: 400 invalid input, 404 not found, 409 conflict, 413 too large, 422 unprocessable file, 429 rate-limited provider, 503 provider unavailable |
| Tracing | Every response has `X-Request-ID`. Send your own (8–64 safe characters) to correlate client and server logs |
| Documentation | Generated from the code: **<http://127.0.0.1:8000/docs>** (interactive) and `/openapi.json`. The contract is designed in DESIGN-001 §11.1 |
| Long work | Uploads return `202 Accepted` and are processed in the background; clients poll `GET /documents/{id}` until no version is `uploaded` or `processing` (`is_processing: false`) |
| Who may call | Only this machine. Requests with a non-loopback `Host`, or changes sent from another website (`Origin`, `Sec-Fetch-Site`), get `403 FORBIDDEN_ORIGIN`. Tools such as curl are unaffected |

### 5.2 Endpoints available now (Phase 7)
| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok", "version": "0.3.0"}` |
| GET | `/api/v1/system/status` | Document and searchable-chunk counts, schema version, index embedding model, whether re-indexing is needed (`reindex_required`, `versions_missing_vectors`), and provider models (never keys) |
| POST | `/api/v1/documents` | Upload a new document (multipart field `file`) → **202** `DocumentDetail` |
| GET | `/api/v1/documents` | `DocumentSummary[]`, most recently updated first |
| GET | `/api/v1/documents/{id}` | `DocumentDetail` with the version history, newest first |
| DELETE | `/api/v1/documents/{id}` | **204**; all versions and files are removed; processing is cancelled |
| POST | `/api/v1/documents/{id}/versions` | Upload a new version → **202** `VersionInfo` |
| POST | `/api/v1/documents/{id}/versions/{vid}/activate` | Approve a ready version for answers → `DocumentDetail` (409 `VERSION_NOT_READY`) |
| DELETE | `/api/v1/documents/{id}/versions/{vid}` | **204** (409 `VERSION_IS_ACTIVE`); deleting the last version deletes the document |
| POST | `/api/v1/documents/{id}/versions/{vid}/retry` | Queue a failed version again → **202** (409 `VERSION_NOT_FAILED`) |

```bash
curl -s -F "file=@guide.md" http://127.0.0.1:8000/api/v1/documents
curl -s http://127.0.0.1:8000/api/v1/documents/<id>
```

```json
{"id": "6a25…", "display_name": "دليل المستخدم", "active_version_id": "b638…",
 "is_processing": false, "created_at": "2026-11-14T20:49:01+00:00", "updated_at": "…",
 "versions": [{"id": "b638…", "version_number": 1, "status": "ready", "stage": null,
               "is_active": true, "original_filename": "دليل المستخدم.md", "format": "markdown",
               "size_bytes": 12034, "page_count": null, "chunk_count": 19,
               "embedding_model": "gemini-embedding-001", "error": null,
               "uploaded_at": "…", "processing_finished_at": "…"}]}
```

A failed version carries `"error": {"code": "PDF_NO_TEXT", "message": "<Arabic>"}`. The conversation endpoints of DESIGN-001 §11.1 are added in Phases 9–10.

### 5.2.1 What happens after an upload

```mermaid
sequenceDiagram
    autonumber
    actor U as 👤 User
    participant A as 🖥️ web (API or page)
    participant S as ⚙️ DocumentService
    participant F as 🗄️ FileStore
    participant W as ⚙️ IngestionWorker (thread)
    participant P as 🔶 ingestion.pipeline
    participant E as ☁️ embedding provider
    participant R as 🗄️ DocumentRepository

    U->>A: POST file
    A->>S: upload_document(name, stream)
    S->>F: receive(): stream to .part, size limit, SHA-256
    S->>S: type by content, UTF-8, duplicate check
    S->>F: accept(): rename to <uuid>.pdf|.md
    S->>R: create document + version + queued job (one transaction)
    S-->>W: wake()
    A-->>U: 202 (status: uploaded)
    W->>R: claim_next_job() → processing
    W->>P: process_file(): extract → clean → chunk (in memory)
    P-->>W: chunks (or an AppError → version failed, Arabic message)
    loop batches of 20, at most one request per 20 s
        W->>E: embed(heading path + text) via port, retried on 429/5xx
        E-->>W: vectors (checked, L2-normalized)
    end
    W->>R: complete_ingestion(): chunks + vectors + ready + approve + index_generation (one transaction)
    Note over W,R: If the version was deleted meanwhile, the stage update before each batch<br/>or the final check finds it gone and nothing is written (DD-02)
```

### 5.2.2 Embeddings and the vector index, in five facts
1. **What is embedded:** for each chunk, its normalized heading path, a newline, then its normalized text (`ingestion/embedding.py::embedding_text`). The headings tell the model which section a passage belongs to (Phase 3 finding).
2. **How provider calls behave:** `ThrottledEmbeddings` keeps requests at least `min_seconds_between_batches` apart; `RetryingEmbeddings` retries 429, 5xx, timeouts, and network errors with backoff (15 s doubling, 5 attempts, configurable in `[ingestion]`), honouring `Retry-After`. Auth errors and malformed responses fail at once. The waits end immediately when the app stops.
3. **One model at a time:** every vector carries its model and dimension; `meta` records the index model. A vector of another model is refused (`REINDEX_REQUIRED`) before any quota is spent, and again inside the storing transaction.
4. **Searchable means active and ready:** `VectorIndex.current()` loads the `active_chunk_vectors` view into a read-only NumPy matrix and reloads only when `meta.index_generation` changes. Phase 8 adds the search over it.
5. **Re-indexing:** `rag reindex` embeds whatever lacks a vector of the configured model into `reindex_staging`, batch by batch, then swaps everything in with one transaction. Interrupted runs resume from staging.

### 5.3 Adding an endpoint (recipe)
1. Write or extend a **service** function that takes and returns plain types or dataclasses.
2. Add a **response model** in `web/api/schemas.py`.
3. Add the **route** in `web/api/<area>.py`. It gets dependencies through `Depends(get_context)`, calls the service, and returns the model.
4. Raise `AppError(ErrorCode.X, …)` for expected failures; never build error responses by hand.
5. Add tests: a service unit test, plus an API integration test that also checks the error case.
6. Update DESIGN-001 §11.1 if the contract changed, and add the endpoint to §5.2 above.

---

## 6. Database and Performance

| Topic | What we do | Why |
|---|---|---|
| Engine | SQLite, one file in `app_data/`, **WAL** mode | Readers never block the background worker; single-user scale (T-05) |
| Integrity | `foreign_keys=ON`, `ON DELETE CASCADE` from versions to chunks, vectors, and jobs; `CHECK` constraints on statuses and vector length | Deleting cannot leave orphans; impossible states are rejected by the database itself |
| Transactions | `db.transaction()` = `BEGIN IMMEDIATE … COMMIT`, rolled back on any error | Multi-row changes are all-or-nothing (DESIGN-001 §7.1) |
| Indexes | One per hot query: duplicate check (`content_hash`), version history, job queue (`status, created_at`), messages in order, conversation list, citations by message and by chunk | Each lookup is O(log n) instead of a table scan |
| Retrieval set | View `active_chunk_vectors`: only **ready, active** versions | Retrieval can never see an inactive or half-processed version |
| Proof | `tests/integration/storage/test_migrations.py` checks `EXPLAIN QUERY PLAN` for every hot query | A future change that drops an index fails CI |
| Similarity search | Exact cosine in NumPy over the active vectors, cached in memory (Phase 7–8) | Measured 0.6–2.3 ms at 20,000 chunks (TECH-001 T-05); far under the 1 s target |

**Version numbers** come from `documents.last_version_number` (migration 0002), so a deleted version's number is never reused and old citations stay unambiguous.

**Schema changes:** add `storage/migrations/000N_<what>.sql`. Never edit an applied migration. The app applies pending migrations at start-up, each in its own transaction.

---

## 7. Where Every Document Lives

| Document | Answers the question | Update it when |
|---|---|---|
| [`README.md`](../README.md) | How do I install, configure, and run it? What data leaves my computer? | Any user-visible change |
| [`CLAUDE.md`](../CLAUDE.md) | How must the engineer work on this project? (Arabic, reference) | Owner decision only |
| [`docs/PROJECT_BRIEF.md`](PROJECT_BRIEF.md) | What is the project and its scope? (Arabic, reference) | Owner decision only |
| [`docs/EXECUTION_PROTOCOL.md`](EXECUTION_PROTOCOL.md) | How are phases planned, approved, and changed? (Arabic, reference) | Owner decision only |
| [`docs/planning/PHASE_0_DISCOVERY_AND_PLAN.md`](planning/PHASE_0_DISCOVERY_AND_PLAN.md) | What is the phase plan and why? | Plan changes |
| [`docs/01_SRS.md`](01_SRS.md) | **What** must the system do? (requirement IDs) | Through change management |
| [`docs/02_SAMPLE_CORPUS.md`](02_SAMPLE_CORPUS.md) | What test data exists and how was it verified? | Corpus or golden-set changes |
| [`docs/03_TECHNOLOGY_EVALUATION.md`](03_TECHNOLOGY_EVALUATION.md) | **Why** these technologies? (measurements, sources) | A technology is reconsidered |
| [`docs/04_ARCHITECTURE_AND_DESIGN.md`](04_ARCHITECTURE_AND_DESIGN.md) | **How** is it built? (architecture, data, pipelines, API) | Any structural change, in the same PR |
| [`docs/05_ENGINEERING_STANDARDS.md`](05_ENGINEERING_STANDARDS.md) | What rules must code and docs follow? | A rule changes (owner approval) |
| [`docs/07_UI_AND_IDENTITY.md`](07_UI_AND_IDENTITY.md) | How does the interface look and behave, and why? (identity, colours, type, patterns, accessibility, assets) | Any UI change |
| `docs/06_DEVELOPER_GUIDE.md` (this file) | Where is everything and how do I work with it? | Structure, endpoints, or workflow change |
| [`docs/DECISIONS.md`](DECISIONS.md) | What was decided, when, and why? | Every approved decision |
| [`CHANGELOG.md`](../CHANGELOG.md) | What changed in each release? | Each phase PR |
| Docstrings in `src/` | What does this function or module do and why? | With the code |

---

## 8. Writing Documentation: the Eight Rules

From STD-001 §14.2, with an example of each:

| # | Rule | Instead of… | Write… |
|---|---|---|---|
| 1 | **Write for a named reader** | (no audience) | "For whoever maintains the ingestion worker" |
| 2 | **Most useful first** | three paragraphs of background, then the command | the command, then the background |
| 3 | **Show, don't tell** | "configure the provider appropriately" | the exact TOML block |
| 4 | **Short, active sentences; consistent terms** | "Chunks may be created by the system when…" | "The chunker splits each section into chunks." |
| 5 | **Link, don't duplicate** | copying the deletion rules | "Deletion follows DESIGN-001 §7.2" |
| 6 | **Evidence over adjectives** | "very fast search" | "0.6 ms at 20,000 chunks (T-05)" |
| 7 | **Keep it current** | docs updated "later" | the doc change in the same commit as the code |
| 8 | **Language** | mixed languages | English for code and docs; Arabic for UI text and owner reports |

## 9. Drawing Diagrams: the Rules

1. **Mermaid only.** Diagrams are text, live next to the prose, and render on GitHub.
2. **One visual language:**

| Shape and colour | Meaning |
|---|---|
| 👤🖥️ blue, rounded | people and interface |
| ⚙️ green, rectangle | our services |
| 🔶 amber, hexagon | a RAG pipeline stage |
| 🗄️ purple, cylinder | stored data |
| ☁️ red, flag shape | external provider |
| 🔧 grey, double-edged box | local tool |

3. **One message per diagram.** If arrows cross, split the diagram.
4. **Validate before committing:** `cd tools/docs && node check_mermaid.mjs ../../docs/*.md ../../README.md`. This renders every diagram with Mermaid 11 and 12; CI runs it too.

---

## 10. Everyday Commands

| Task | Command |
|---|---|
| Install or update the environment | `uv sync` |
| Run the app | `uv run rag serve` → <http://127.0.0.1:8000> |
| Check the environment | `uv run rag check` |
| Re-embed after an embedding-model change (app stopped) | `uv run rag reindex` |
| All tests | `uv run pytest` |
| One test file, verbose | `uv run pytest tests/integration/storage/test_migrations.py -v` |
| Coverage report | `uv run pytest --cov` |
| Lint, format, types, layers | `uv run ruff check` · `uv run ruff format` · `uv run mypy` · `uv run lint-imports` |
| Regenerate the braid logo after a colour change | `python tools/brand/make_braid.py` |
| Add a runtime or dev dependency | `uv add <pkg>` or `uv add --dev <pkg>`, then explain why in the commit (STD-001 §2.2) |
| Before every commit | the review checklist, STD-001 §13 |
