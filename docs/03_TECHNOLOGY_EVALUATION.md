# Technology Evaluation and Selection

| Item | Value |
|---|---|
| Document ID | TECH-001 |
| Phase | Phase 3: Technology Evaluation and Selection |
| Status | **Draft, in progress.** Embedding and LLM measurements are pending provider API keys (D-025). Every choice below is a **proposal** until the owner approves it at the end of the phase. |
| Date | 2026-11-13 |
| Inputs | `docs/01_SRS.md` (requirements), `docs/02_SAMPLE_CORPUS.md` (corpus and findings), `docs/DECISIONS.md` |
| PoC code | `poc/extraction/`, `poc/retrieval/`, `poc/storage/` |

---

## 1. Method

### 1.1 Evidence rules (D-026)
Choices rest only on:
1. **Requirements**, including the target environment: the owner's Windows machine (D-017), a single user (D-009), and free hosted providers (D-010).
2. **Authoritative sources:** official documentation, licenses, official pricing and data-usage terms, and recognised benchmarks.
3. **Reproducible measurements** on the project's Arabic corpus and golden set, with pinned versions.

What happens to be installed or reachable in the development container is **never** a criterion. Third-party aggregator sites are used only as leads. Official pages were consulted through search restricted to each vendor's own domain; the URLs are listed in §6.

### 1.2 Criteria
| Criterion | Why it matters here | Source |
|---|---|---|
| Requirements fit | The proposal must satisfy the relevant FR/NFR | SRS |
| Arabic quality (measured) | Arabic is the core data and query language | D-002, NFR-LNG |
| Data consistency | No orphaned data; atomic version switch | FR-DOC-07, FR-VER-04, FR-ING-13 |
| Windows operability | One-machine install from a clean environment | D-017, NFR-OPS-01 |
| Licensing | No license that constrains the project | Professional practice |
| Maturity and maintenance | Low risk of abandonment or breaking churn | Professional practice |
| Transparency and learning value | Each RAG stage must be understood, not used as a black box | CLAUDE.md §3, §6 |
| Simplicity | The simplest design that meets the requirements | CLAUDE.md §5 |
| Cost and data terms | Free tiers only; data-usage terms disclosed | D-010, NFR-PRV-01 |

### 1.3 How measurements should be read
- The golden set has 43 answerable questions in the default state, so differences smaller than about **±10–15 points** on Hit@k are within noise (CORPUS-001 §4.3).
- The corpus is small (76 chunks at the baseline setting), which makes retrieval easier than in a large knowledge base. Relative comparisons between options are more informative than absolute scores.

---

## 2. Summary of Proposals

| # | Layer | Proposal | Status |
|---|---|---|---|
| T-01 | Backend language | **Python** (3.12 or later) | Proposed |
| T-02 | Web/API framework | **FastAPI** | Proposed |
| T-03 | User interface | **Server-rendered HTML (Jinja2) + HTMX**, Arabic right-to-left | **Approved** (D-027) |
| T-04 | Background processing | **In-process worker** with job state persisted in the database | Proposed |
| T-05 | Storage | **SQLite** (one file: metadata, chunks, vectors, conversations) with **exact NumPy similarity search** | Proposed (sqlite-vec kept as alternative) |
| T-06 | PDF text extraction | **pdftotext (Poppler)** via subprocess | **Approved** (D-028); Windows install step accepted |
| T-07 | Markdown parsing | **markdown-it-py** | Proposed |
| T-08 | Arabic normalization | Basic set (NFKC, tashkeel/tatweel, digits) for indexing; original text kept for display | Proposed; refined by the embedding PoC |
| T-09 | Chunking | **Own implementation**: heading-aware, size-bounded, overlapping | Proposed; size tuned after the embedding PoC |
| T-10 | Embedding provider | Gemini vs Cohere vs Jina (Mistral optional) | **Pending measurement (keys)** |
| T-11 | LLM provider (generation) | Gemini vs Groq-hosted models vs Mistral | **Pending measurement (keys)** |
| T-12 | LLM-as-judge (evaluation only) | A different provider from T-11 | Pending T-11 |
| T-13 | Provider integration | **OpenAI-compatible interface** as the common adapter, plus native adapters where measurement shows they matter | Proposed |
| T-14 | RAG orchestration | **Own pipeline** (no LangChain, LlamaIndex, or Haystack) | Proposed |
| T-15 | Testing and quality tooling | **pytest**, HTTP mocking, **ruff**; Playwright for end-to-end tests (Phase 10) | Proposed |

---

## 3. Application Stack

### T-01 Backend language: Python
| Option | For | Against |
|---|---|---|
| **Python** | The PDF, text, and evaluation tooling measured in this phase is Python (pypdf, pypdfium2, NumPy). It is the dominant language for AI engineering, which serves the learning goal (CLAUDE.md §3). Official Windows installers exist. | Slower than compiled languages; irrelevant at this scale. |
| TypeScript (Node.js) | One language for UI and API. | Weaker document-processing and numeric ecosystem for this use; the Arabic PDF findings were obtained with Python tools. |

**Proposal: Python.** The exact version is pinned in Phase 5.

### T-02 Web/API framework: FastAPI
| Option | For | Against |
|---|---|---|
| **FastAPI** | Request/response validation with Pydantic (FR-DOC-03, FR-RET-01). Generates an OpenAPI description automatically, which supports the API-design learning goal and the Phase 4 API contracts. Async I/O suits waiting on provider calls. | More concepts than Flask (async, dependency injection). |
| Flask | Minimal and simple. | Validation and API documentation must be added by hand. |
| Django | Batteries included (ORM, admin). | Much of it is unused; its weight is not justified for a single-user app (CLAUDE.md §5). |

**Proposal: FastAPI.**

### T-03 User interface: Jinja2 + HTMX (approved, D-027)
| Option | For | Against |
|---|---|---|
| **Jinja2 templates + HTMX** | One language and runtime; no Node.js on the owner's machine. Right-to-left via standard `dir="rtl"`. Partial page updates (processing status, FR-UI-03) without a JavaScript framework. The smallest moving parts. | Less of a frontend portfolio piece; complex client-side interactions are harder. |
| React SPA (built with Vite) | Industry-standard frontend skills for the portfolio; rich interactivity. | A second language and toolchain, and a build step (Node.js needed to build). More code for the same features. |
| Streamlit or Gradio | Fastest to prototype. | Limited control over layout and right-to-left rendering; does not reflect a real web-app architecture (BR §1). Not recommended. |

**Recommendation:** Jinja2 + HTMX, for the simplicity rule (CLAUDE.md §5) and Windows operability. The backend still exposes a documented JSON API, so the UI can be replaced later. **If frontend skills matter for the portfolio, React is a reasonable choice at the cost of more complexity.** This trade-off is the owner's to make.

### T-04 Background processing: in-process worker
| Option | For | Against |
|---|---|---|
| **In-process worker** (a background thread or task) with job state in the database | Meets FR-ING-01 and FR-ING-02. Recovery after restart (FR-ING-14) works because state is persisted. Nothing extra to install. | Work stops while the app is stopped; acceptable for a single user. |
| Celery, RQ, or Dramatiq with Redis | Robust distributed queues. | Requires a broker service on Windows; no benefit for one user (CLAUDE.md §5, §7). |

**Proposal: in-process worker.**

### T-05 Storage: SQLite with exact NumPy search
The requirements that drive this choice are consistency requirements:
- delete with no orphaned data (FR-DOC-07);
- atomic version activation (FR-VER-04);
- a version becomes retrievable only when complete (FR-ING-13).

These are simplest to guarantee when metadata, chunks, and vectors live in **one transactional store**.

| Option | Consistency with metadata | Windows install | Notes |
|---|---|---|---|
| **A. SQLite + vectors as BLOBs + exact NumPy search** | One ACID transaction covers everything | Python standard library + NumPy | Exact results; filtering is done in SQL before search, so it is always correct |
| B. SQLite + sqlite-vec (vec0) | Same database, so transactional | Wheel available for Windows (0.1.9); requires Python's SQLite extension loading | Vector search in SQL. Stable release 0.1.9; newer releases are alphas. A reported issue: filtered KNN can return fewer than k results in some query shapes. |
| C. Chroma, Qdrant (local mode), or LanceDB beside a metadata database | Two stores, so every write is a dual write that needs compensation logic | pip packages | Qdrant describes local mode as for testing and small data. LanceDB versions per table, but not across stores. |
| D. PostgreSQL + pgvector | Full ACID | A PostgreSQL server to install and run on Windows | Correct but heavy for a single-user desktop app |

**Measurement** (`poc/storage/bench_vector_search.py`): 20,000 chunks (NFR-PRF-05), 30% inactive versions, top-10, 50 queries, median latency on the same machine:

| Dimension | A: NumPy exact | B: sqlite-vec 0.1.9 | B agrees with exact | Startup cost of A |
|---|---|---|---|---|
| 768 | 0.63 ms | 20.5 ms | 100% (no short results) | 68 ms to load the active vectors |
| 1024 | 0.70 ms | 28.6 ms | 100% | 94 ms |
| 3072 | 2.30 ms | 86.5 ms | 100% | 285 ms |

Both are far below the 1-second target (NFR-PRF-02).

**Proposal: A.** It has no native extension, is exact by construction, and makes the similarity computation explicit, which serves the learning goal. Its cost is an in-memory copy of the active vectors that must be refreshed after writes (a design point for Phase 4). **B remains the alternative** if a later requirement favours SQL-side search. Option C is rejected because of dual-write consistency; option D because of its installation weight.

---

## 4. Document Processing

### T-06 PDF text extraction: pdftotext (Poppler)
**Text quality** (`poc/extraction/`, Arabic PDFs from the corpus; mean of 3 PDFs):

| Extractor | Letter error | Letter CER | Word recall | License | Windows |
|---|---|---|---|---|---|
| **pdftotext (Poppler)** | **0.1%** | **1.9%** | 85.8% | GPL (separate executable) | Separate install (conda-forge `poppler` win-64 build, or a zip of those binaries) |
| pypdfium2 | 2.1%* | 7.1% | **93.4%** | Apache-2.0 / BSD-3 | pip wheel |
| PyMuPDF | 2.8% | 67.0% (reversed order) | 90.9% | **AGPL-3.0** or commercial | pip wheel |
| pypdf | 2.1% | 66.9% (reversed order) | 86.7% | BSD-3 | pip wheel |
| pdfminer.six / pdfplumber | 2.1% | 80.3% | 9.4% | MIT | pip wheel |

\* Mostly the page footer, which pdfium emits with reversed letters.

**Effect on retrieval** (`poc/retrieval/run_lexical.py`; the same BM25 retriever and chunking, only the extractor changes):

| Extractor | Evidence entries still intact after extraction | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|---|
| **pdftotext** | **57 / 57** | 0.67 | 0.81 | **0.93** | **0.766** |
| pypdfium2 | 52 / 57 | 0.63 | 0.74 | 0.81 | 0.711 |

pypdfium2 garbles letter order around shadda (e.g., «تشفّر» → «تفشر»), around Latin-and-digit runs («AES-256» → «256AES»), and in some table cells. As a result, five evidence passages no longer exist in the extracted text and cannot be retrieved by any method.

**Decision: pdftotext** (approved by the owner, D-028), invoked as a separate process. Consequences:
- **Windows installation step:** a conda-forge Poppler build. This is documented in the README and checked at start-up (FR-CFG-04).
- **Re-verification on Windows:** Poppler's version there may differ from the one measured (D-026, NFR-OPS-04, P-011).
- **Licensing:** Calling a GPL program as a separate executable is generally treated as aggregation, not linking. This is an engineering note, not legal advice.

The extractor sits behind an interface, so pypdfium2 can replace it if the Windows installation proves unacceptable, at the measured retrieval cost.

### T-07 Markdown parsing: markdown-it-py
It is CommonMark-compliant with table support (MIT license), and is the Python port of the parser already used to render the corpus PDFs (D-023). Headings provide the section structure for chunking (FR-ING-06).

### T-08 Arabic normalization
BM25 measurements, one factor at a time (pdftotext, 800/150 chunks):

| Normalization | Hit@3 | Hit@5 | MRR |
|---|---|---|---|
| Basic: NFKC, tashkeel/tatweel removal, Arabic-Indic → Western digits | 0.81 | 0.93 | 0.766 |
| + alef / yaa / taa-marbuta unification | 0.81 | 0.93 | 0.766 |
| + alef/yaa/taa + light prefix stemming (ال، وال، بال …) | 0.88 | 0.93 | 0.783 |

**Proposal:**
- The basic set is required, because D05 uses Arabic-Indic digits and NFKC folds presentation forms (FR-ING-04).
- The original text is always kept for display and citation (FR-ING-08).
- Extra unification and stemming showed no meaningful lexical gain within the noise margin (§1.3). They will be re-tested with embeddings and kept only if they help.

### T-09 Chunking: own implementation
Requirements specific to this project make a generic splitter a poor fit:
- heading-aware sections for Markdown and for numbered PDF headings, including pdftotext's «.٢» heading order;
- the heading path recorded in metadata (FR-ING-10);
- table rows kept together (FR-ING-09).

Size sensitivity with BM25: 500/100, 800/150, and 1200/200 characters all give Hit@5 = 0.93, with MRR between 0.760 and 0.766. The small corpus does not discriminate. **The final size is chosen in the embedding PoC**, because embedding models are more sensitive to chunk length.

---

## 5. Model Providers

### 5.1 Facts from official sources
| Provider | Free access | Limits | Data use on free tier | Relevant models (per official docs, subject to change) |
|---|---|---|---|---|
| **Google Gemini API** | Free tier for selected models | Not published per model; shown in AI Studio | Pricing page: content **is used to improve Google's products** on the free tier (not on paid) | Embeddings: Gemini Embedding (`gemini-embedding-001`), Gemini Embedding 2 (free input). Generation: Flash-family models |
| **Groq** | Free plan | Per model and per organisation; the exact figures are on the account's limits page | Not stated in the pages consulted | Production: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`. Preview: Qwen3 family. No embedding models |
| **Cohere** | Trial key | 1,000 API calls per month; Embed 2,000 inputs per minute (trial) | Trial keys **may not be used for production or commercial purposes** | Embeddings with Arabic support: `embed-multilingual-v3.0`, `embed-v4.0` (both listed in a retirement notice), `embed-v5.0-pro` (newer, 100+ languages) |
| **Jina AI** | Free tokens with each new key | Free: 100 RPM, 100K TPM | Not stated in the pages consulted | `jina-embeddings-v3`: 89 languages, 8,192-token input |
| **Mistral** | Free mode (the default for new accounts) | Lowest tier; intended for evaluation and prototyping | **Inputs and outputs may be used for training**; an opt-out exists in the Admin panel | Mistral Saba (the Arabic-focused model) was **retired on 2025-09-30**; Mistral recommends Mistral Small 4 |

No official Arabic-specific retrieval scores were found for any candidate. Google cites leading results on the MTEB Multilingual leaderboard for its embedding model, but that is multilingual, not Arabic-specific. **Arabic suitability is therefore decided by measurement on the golden set.**

### T-10 Embedding provider: pending measurement
The harness is ready (`poc/retrieval/run_embeddings.py`) and was checked end-to-end with a non-model test double. It reports:
- Hit@1/3/5, Recall@5, and MRR on the same chunks as the BM25 baseline (Hit@5 = 0.93, MRR = 0.766). An embedding model must beat this baseline to justify its use.
- **AUROC of the top similarity score, answerable vs. unanswerable.** This is the evidence for whether a relevance threshold (FR-RET-06) can separate the two groups for that model.
- Native API vs. OpenAI-compatible endpoint where both exist, because compatibility endpoints may not expose query/document task types.

### T-11 / T-12 LLM provider and judge: pending measurement
Plan once keys exist:
- generate answers for the golden set with each candidate under the same prompt;
- measure refusal accuracy, citation validity, and LLM-as-judge faithfulness and correctness, with the judge from a different provider than the generator (FR-EVAL-04);
- record free-tier limits encountered and latency.

### T-13 Provider integration: OpenAI-compatible interface
Official documentation confirms OpenAI-compatible chat and/or embedding endpoints for:
- **Gemini** (`/v1beta/openai/`);
- **Groq** (`https://api.groq.com/openai/v1`);
- **Cohere** (Compatibility API);
- **Ollama**, a local model server (`http://localhost:11434/v1/`).

Using this interface as the common adapter means **switching providers is a configuration change** (D-010), and a **future local provider needs no new adapter** (D-013). Native adapters are added only where measurement shows a quality gain, for example embedding task types.

---

## 6. RAG Orchestration and Tooling

### T-14 RAG orchestration: own pipeline
| Option | For | Against |
|---|---|---|
| **Own pipeline** (thin, explicit modules for each stage in SRS §3) | Every stage is visible and testable, as CLAUDE.md §6 requires. Arabic extraction, normalization, versioning, and citation validation need custom code in any case. Few dependencies. | More code to write; manageable at this scope. |
| LangChain, LlamaIndex, or Haystack | Ready-made components and integrations. | Abstractions hide the stages the project is meant to teach. Large dependency trees with frequent API changes. Their generic splitters and loaders do not handle the Arabic PDF findings or our version model. |

**Proposal: own pipeline.** Libraries are used for well-defined sub-tasks only: HTTP, PDF and Markdown parsing, numeric search, and validation.

### T-15 Testing and quality tooling
- **pytest** for unit and integration tests.
- **HTTP mocking** so automated tests never call real providers (NFR-MNT-02). Real-provider tests are separate and opt-in.
- **ruff** for linting and formatting (NFR-MNT-04).
- **Playwright (Python)** for end-to-end UI tests in Phase 10.
- CI (P-008) is decided in Phase 5.

---

## 7. Open Items and Risks

| Item | Status |
|---|---|
| Provider API keys (Gemini, Groq, Cohere, Jina; Mistral optional) | The owner will create the accounts; the T-10, T-11, and T-12 measurements are waiting on them |
| T-03 UI approach | Resolved: Jinja2 + HTMX (D-027) |
| Poppler on Windows (T-06) | Installation step and re-verification on Windows |
| NFR-LNG-02 (P-011) | With pdftotext: 1.9% letter CER overall, but 2.6–3.1% on the table-heavy pricing PDFs. A redefinition is proposed with the final report |
| Free-tier data terms | Gemini and Mistral free tiers may use the data. Acceptable for the fictional corpus; must be revisited before any real data |
| Free-tier changes | Limits and model lists change frequently; mitigated by T-13 and by configurable model IDs |

---

## 8. Sources
Official vendor pages (consulted through search restricted to each vendor's domain):
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini OpenAI compatibility: https://ai.google.dev/gemini-api/docs/openai
- Gemini Embedding GA (Google Developers Blog): https://developers.googleblog.com/gemini-embedding-available-gemini-api/
- Gemini Embedding paper: https://arxiv.org/abs/2503.07891
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq models: https://console.groq.com/docs/models
- Groq OpenAI compatibility: https://console.groq.com/docs/openai
- Cohere rate limits and trial keys: https://docs.cohere.com/docs/rate-limits
- Cohere pricing: https://cohere.com/pricing
- Cohere embeddings: https://docs.cohere.com/docs/embeddings
- Cohere Compatibility API: https://docs.cohere.com/docs/compatibility-api
- Jina Embeddings: https://jina.ai/embeddings/
- jina-embeddings-v3: https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/
- Mistral training opt-out: https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training
- Mistral rate limits: https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them
- Mistral Saba (retired): https://docs.mistral.ai/models/mistral-saba-25-02
- Ollama OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
- sqlite-vec: https://github.com/asg017/sqlite-vec
- sqlite-vec metadata filtering: https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/index.html
- Chroma delete and filters: https://docs.trychroma.com/docs/collections/delete-data
- Qdrant local mode: https://qdrant.tech/documentation/quickstart/
- LanceDB versioning: https://docs.lancedb.com/tables/versioning
- Poppler on conda-forge (win-64): https://anaconda.org/conda-forge/poppler
