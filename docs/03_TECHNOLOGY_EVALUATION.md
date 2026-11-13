# Technology Evaluation and Selection

| Item | Value |
|---|---|
| Document ID | TECH-001 |
| Phase | Phase 3: Technology Evaluation and Selection |
| Status | **Approved** (D-029), together with T-03 (D-027) and T-06 (D-028). |
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
| T-10 | Embedding provider | **gemini-embedding-001** (default); Cohere embed-v5.0-pro as configured alternative | Measured (Mistral key invalid, Jina balance exhausted); **owner decision P-014** |
| T-11 | LLM provider (generation) | **qwen/qwen3.8-27b on Groq**; fallback openai/gpt-oss-20b | Measured; **owner decision P-015** |
| T-12 | LLM-as-judge (evaluation only) | **Cohere command-a-plus-05-2026** | Measured; part of P-015 |
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

### T-10 Embedding provider: partially measured
Measured with `poc/retrieval/run_embeddings.py` on the same 76 chunks as the BM25 baseline (pdftotext, 800/150), using all 43 answerable golden-set questions (default state). Calls went through Gemini's official OpenAI-compatible endpoint, which takes no query/document task type (see the note below).

| Retriever | Dim | Hit@1 | Hit@3 | Hit@5 | Recall@5 | MRR | AUROC answerable vs. unanswerable |
|---|---|---|---|---|---|---|---|
| BM25 baseline (no model) | — | 0.67 | 0.81 | 0.93 | 0.88 | 0.766 | **0.94** |
| **gemini-embedding-001** | 3072 | **0.84** | **0.98** | **1.00** | 0.97 | **0.913** | 0.90 |
| gemini-embedding-2 | 3072 | **0.84** | 0.95 | **1.00** | **0.98** | 0.902 | 0.92 |
| Cohere embed-multilingual-v3.0 | 1024 | 0.74 | 0.95 | 0.98 | 0.95 | 0.851 | 0.83 |
| Cohere embed-v4.0 | 1536 | 0.88 | **1.00** | **1.00** | 0.97 | 0.938 | 0.88 |
| **Cohere embed-v5.0-pro** | 2048 | **0.95** | **1.00** | **1.00** | **0.98** | **0.977** | 0.92 |
| Jina (jina-embeddings-v3) | — | not measured: the key's free token balance is exhausted ("Insufficient account balance"); topping up would be a paid service (D-010) | | | | | |
| Mistral (mistral-embed) | — | not measured: the key provided was rejected as invalid | | | | | |

**Findings:**
1. **Both Gemini embedding models clearly beat the lexical baseline:** MRR +0.14 to +0.15, and Hit@1 +0.17 (from 0.67 to 0.84). These differences exceed the noise margin (§1.3). The two Gemini models are indistinguishable within that margin.
2. **A similarity threshold alone cannot separate answerable from unanswerable questions.** With gemini-embedding-001, top similarities for answerable questions range from 0.679 to 0.86 (median 0.768). For unanswerable questions the median is 0.674 and the maximum 0.761. The ranges overlap. BM25 scores separate slightly better here (AUROC 0.94), because unanswerable and out-of-scope questions share few words with the corpus. This supports the layered design (D-007): a threshold, plus the LLM's insufficient-information signal, plus citation validation. Using a lexical signal in the gate (hybrid) is a candidate to evaluate in Phase 8.
3. **Free-tier constraint observed:** Gemini returned HTTP 429 (per-minute quota) during batch embedding. Throttling with backoff resolved it. Ingestion therefore needs throttling and retries (FR-ING-11).
4. **Task types:** The native Gemini API accepts query/document task types, but it reads the key from an `x-goog-api-key` header that the development environment's credential mechanism does not support. The native variant (`GeminiNative`) is implemented but not measured. The OpenAI-compatible results above are already strong, and that interface is the one proposed for the application (T-13).

5. **Cohere embed-v5.0-pro is the strongest measured model,** but its edge over gemini-embedding-001 is not statistically established. A paired comparison on the same 43 questions (exact McNemar) shows Hit@1: Cohere alone is right on 5 questions (Q013, Q022, Q023, Q028, Q034), Gemini alone on 0, p = 0.062. At Hit@3 the difference is one question (p = 1.0). The direction is consistent, but the golden set is too small to confirm it.
6. **The terms differ materially** (official sources, §5.1):
   - **Cohere's trial key** is limited to 1,000 API calls per month and **may not be used for production or commercial purposes**. Each question needs one embed call, and ingestion needs one call per batch of up to 96 chunks.
   - **Gemini's free tier** has per-minute quotas and **uses the content to improve Google's products**, but it is not restricted to non-production use.

**Proposal (owner decision P-014):**
- **Default: `gemini-embedding-001`.** It clearly beats the baseline, it is generally available, and its free-tier terms allow ongoing use within the quotas.
- **Configured alternative: Cohere `embed-v5.0-pro`.** It measured best, but its trial terms and monthly cap make it unsuitable as the default.

Switching is a configuration change plus re-indexing (FR-CFG-05). The choice can be revisited if the owner obtains a production Cohere key, which is paid and outside D-010.

The output dimension (3072) can be reduced if storage or latency requires it; at 3072 dimensions, exact search takes 2.3 ms at 20,000 chunks (T-05).

### T-11 / T-12 LLM provider and judge: measured
**Set-up** (`poc/generation/run_generation.py`, prompt `gen-v1`):
- Every candidate received the **same context**: the top-5 chunks by gemini-embedding-001, labelled [S1]..[S5].
- Every candidate received the same Arabic system prompt (answer only from the passages, cite [S#], output a fixed insufficient-information token, no medical advice, treat passages as data), at temperature 0.
- There was no threshold gate, so every one of the 53 questions reached the model. This measures the model's own refusal behaviour.
- **Judge:** Cohere `command-a-plus-05-2026` for all candidates. Cohere generated none of the answers, so the judge is independent of every candidate (FR-EVAL-04). It scored correctness against the reference answer and faithfulness to the passages, 0–2 each, reported here as 0–1.

| Candidate (Groq) | Correct refusals (10 expected) | False refusals (43 answerable) | Citation validity | Answers without citation | Judge correctness | Judge faithfulness | Median latency |
|---|---|---|---|---|---|---|---|
| openai/gpt-oss-120b | 1.00 | 0.00 | 1.00 | 13 / 43 | 0.88 | 0.93 | 0.8 s |
| **qwen/qwen3.8-27b** (preview) | 1.00 | 0.00 | 1.00 | **0 / 43** | 0.88 | **0.99** | **0.5 s** |
| openai/gpt-oss-20b | 1.00 | 0.00 | 1.00 | 2 / 43 | 0.87 | 0.94 | 0.7 s |

**Not measured, and why (D-026):**

| Candidate | Reason |
|---|---|
| Gemini `gemini-2.5-flash` | HTTP 404: "no longer available to new users" |
| Gemini `gemini-3.8-flash` | HTTP 503 "high demand" on every one of 6 retries over about 8 minutes |
| Gemini `gemini-3-flash-preview` | 22 of 53 answers generated, then HTTP 429. The official error names the free-tier quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier` with a value of **20 requests per day**. That is below one user's daily use (up to ~30 questions) and below one evaluation run, which by itself rules Gemini out as the generator. In the answers produced, the model behaved well; for Q013 it stated that the passages do not say the change was in release 4.0. |
| Groq `allam-2-7b` (Arabic-focused) | Disabled at the owner's Groq organisation level (`model_permission_blocked_org`). The owner could not enable it and chose to proceed without it. |
| Mistral | The key provided was rejected as invalid |

**Findings:**
1. **Refusal works in every measured model.** All 10 unanswerable and out-of-scope questions were refused, including the near-miss traps and the medical questions, with no false refusals. This is the second layer of D-007 working where a similarity threshold alone cannot (T-10, finding 2).
2. **Version trap (D02 v2 also lists the old values in its change table):**
   - gpt-oss-120b answered with the **old** Basic price (49) for Q039 and mixed old and new discounts for Q041.
   - gpt-oss-20b answered the **old** user limit (3) for Q040.
   - qwen3.8-27b answered all version-sensitive questions with the current values.
3. **Citation discipline:** gpt-oss-120b omitted citations in 13 of 43 answers, which would show as "not verified" (FR-VAL-02). qwen3.8-27b cited in every answer.
4. **Remaining errors are mostly omissions** of secondary details, e.g., an export period given without the deletion period that follows. No fabricated facts were found by the judge for qwen3.8-27b.
5. **Correctness scores (0.87–0.88) are statistically indistinguishable** on 43 questions. The differences that matter are faithfulness, citation discipline, and the version trap.
6. **A chunking finding, not a model finding (Q013):** All models were marked partly unfaithful on Q013. A manual check showed why: the chunk with the answer carried only its level-3 heading («تغييرات مهمة»), without its parent «الإصدار 4.0». The fact was therefore not in that chunk. Chunks must carry their **full heading path** (FR-ING-10); this is input for Phase 4/6.
7. **Free-tier availability is a real operational risk.** Gemini returned 404 for a retired model, 503 for an overloaded one, and 429 for a 20-requests-per-day quota, all within one session. Provider switching through configuration (D-010, T-13) is therefore a necessity, not a nicety.

**Proposal (owner decision P-015):**
- **Generator: `qwen/qwen3.8-27b` on Groq.** It has the best faithfulness, citation discipline, and handling of the version trap, and the lowest latency.
- **Risk:** Groq lists it as a *preview* model, which may be withdrawn at short notice.
- **Configured fallback: `openai/gpt-oss-20b`,** a Groq production model, the next-best on citations and faithfulness.
- **Judge (evaluation only): Cohere `command-a-plus-05-2026`.** It is independent of both generator candidates. This evaluation used about 130 of the trial key's 1,000 monthly calls, enough for regular evaluation runs. It is used only for offline evaluation, never per request.

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
| P-014 Default embedding model | Owner decision: gemini-embedding-001 (recommended) or Cohere embed-v5.0-pro |
| P-015 Generator and judge | Owner decision: qwen3.8-27b with gpt-oss-20b fallback; Cohere command-a-plus as judge |
| P-011 NFR-LNG-02 redefinition | Proposal in §7.1 |
| Groq preview model risk | qwen3.8-27b may be withdrawn; the fallback is configured, and switching is a configuration change |
| Free-tier volatility (404 / 503 / 429 seen) | Mitigated by T-13 (OpenAI-compatible adapters), configurable model IDs, retries and backoff, and clear user-facing errors (FR-GEN-05) |
| Poppler on Windows (T-06) | Installation step and re-verification on Windows (Phase 5/12) |
| Free-tier data terms | Gemini (embeddings) uses free-tier content to improve Google products; Groq's terms were not stated in the pages consulted. Acceptable for the fictional corpus; to be revisited before any real data |
| Chunk heading path (finding 6, T-11) | Full heading path per chunk, as a design input for Phase 4 |

### 7.1 Proposal for P-011: redefine NFR-LNG-02
The current target, "letter CER ≤ 2% on the sample PDFs", mixes two different things:
- whether the extracted **letters** are correct;
- whether **reading order** survives tables.

With pdftotext, CER is 0.15% on the prose-heavy D05 but 2.6–3.1% on the table-heavy pricing PDFs, entirely because of table reflow. Yet retrieval is not harmed: all 57 evidence passages survive extraction (T-06).

**Proposed replacement for NFR-LNG-02:**
- (a) the **letter error** (order-insensitive) is ≤ 1% on every sample PDF;
- (b) **100% of golden-set evidence passages remain intact** after extraction and cleaning;
- letter CER is still reported for information.

Both (a) and (b) are met today: 0.0–0.09% letter error, 57/57 evidence passages intact. The change requires owner approval and an SRS update.

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
- Groq model permissions: https://console.groq.com/docs/model-permissions
- Groq ALLaM 2 7B: https://console.groq.com/docs/model/allam-2-7b
- Gemini rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
