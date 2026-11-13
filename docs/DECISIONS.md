# Decision Log

This log records decisions explicitly approved by the project owner. Each decision is also reflected in the relevant reference document (`docs/PROJECT_BRIEF.md`, `docs/EXECUTION_PROTOCOL.md`, or `CLAUDE.md`). Changes to an approved decision follow the change-management procedure in `docs/EXECUTION_PROTOCOL.md` §8.

Status values: **Approved** (decided by the owner) · **Superseded** (replaced by a later decision) · **Pending** (open, with the phase by which it must be resolved).

---

## D-001 — Completion of the truncated reference documents
- **Date:** 2026-11-13 · **Status:** Approved
- **Context:** All three reference documents ended mid-sentence in the initial commit (sizes of about 8.5 KB each, which suggests a size limit during copy or upload). Sections that were probably lost: the end of `CLAUDE.md` §7 and any later sections; `EXECUTION_PROTOCOL.md` from §5 onward; `PROJECT_BRIEF.md` after §5.
- **Decision:** The owner asked Claude to complete the missing parts consistently with the existing text and the decisions below. The completed text was **written by Claude**; it is not a recovery of the original wording. Existing text was not modified, except to finish the two sentences that were cut off.
- **Added sections:**
  - `CLAUDE.md`: §7 completed, plus new §8–§13.
  - `EXECUTION_PROTOCOL.md`: §5 completed, plus new §6–§11.
  - `PROJECT_BRIEF.md`: §5 completed, plus new §6–§11.
- **Consequence:** If the original full documents surface, they should be compared with these completions and any differences resolved with the owner.

## D-002 — Knowledge-base language: Arabic
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** Sample knowledge documents, user questions, and generated answers are in Arabic.
- **Consequences:**
  - The embedding model must be evaluated for Arabic retrieval quality (measured in Phase 3, not assumed).
  - Arabic text normalization needs explicit, justified rules: diacritics, alef variants, tatweel, and similar.
  - Arabic PDF text extraction is a known high risk (reversed letter order, presentation forms) and must be benchmarked.
  - The UI must render right-to-left content correctly.

## D-003 — Supported file formats: text-based PDF and Markdown
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** Only text-based (not scanned) PDF and Markdown are supported. OCR, DOCX, images, and HTML are out of scope.
- **Consequence:** The sample corpus must include at least one document in each format.

## D-004 — Model providers: free, switchable via API
- **Date:** 2026-11-13 · **Status:** Superseded by D-010 (narrowed to hosted free tiers)
- **Decision:** LLM and embedding providers must be free of charge and accessed through an API: either free tiers of hosted providers, or open models served locally behind a local API. Providers must be switchable through configuration without changing RAG pipeline logic.
- **Consequences:**
  - A provider abstraction is required for the LLM and the embeddings.
  - Free-tier rate limits are a design constraint, especially for 15–30 users (see D-006).
  - Free-tier data-usage terms must be documented, because document content is sent to the provider.
  - Switching the embedding model invalidates stored vectors, so the model ID must be stored with the vectors and re-indexing must be supported.
  - The concrete providers will be selected in Phase 3.

## D-005 — Deployment: the owner's machine
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The application initially runs on the owner's machine.
- **Consequence:** Installation must work from a clean environment on that machine. Its operating system is still pending (P-004).

## D-006 — Users: 15–30, no authentication
- **Date:** 2026-11-13 · **Status:** Superseded by D-009
- **Decision:** The system serves about 15–30 users over the local network, with no authentication.
- **Consequences:**
  - The system must not be exposed to the public internet.
  - Concurrent requests must be handled safely.
  - Document processing must not block chat.
  - Without identity, the following must be decided: data ownership, conversation-history separation, and who may delete documents (P-001).
- **Note:** This supersedes the single-user recommendation (Q7) in the Phase 0 report.

## D-007 — Answer verification level
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:**
  - **At runtime (every request):** a minimum retrieval-score threshold (calibrated experimentally), plus validation that every citation refers to a chunk that was actually retrieved.
  - **In evaluation only:** LLM-as-judge for faithfulness and answer correctness.
- **Consequence:** At runtime, verification checks structure: the threshold and that citations are valid. It does not check whether the answer's meaning is supported by the cited text; that is measured offline. This is how the brief's requirement in §3 (Generation, item 5) is met, as documented in `PROJECT_BRIEF.md` §9.

## D-008 — Documentation and code language: English
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** English is used for source code, comments, identifiers, Git messages, the README, and all technical documentation produced during the project.
- **Clarifications (proposed by Claude, open to change):**
  - The three reference documents stay in Arabic, their original language.
  - Communication and phase reports to the owner are in Arabic.
  - The Phase 0 report (`docs/planning/PHASE_0_DISCOVERY_AND_PLAN.md`) was written in Arabic before this decision and is kept as is.

## D-009 — Single user, no authentication
- **Date:** 2026-11-13 · **Status:** Approved (supersedes D-006)
- **Decision:** The system serves a single user on their own machine, with no authentication.
- **Consequences:**
  - There is one knowledge base and one conversation history, both belonging to that user. This resolves the old P-001 and is consistent with the brief's "private knowledge base" (§1).
  - Access is restricted to the local machine: the server binds to localhost and is not exposed to the network or the internet.
  - Multi-user support is out of scope.
  - Document processing must still not block chat.

## D-010 — Model providers: hosted free tiers, switchable via API
- **Date:** 2026-11-13 · **Status:** Approved (supersedes D-004; amended by D-013 regarding local models)
- **Decision:** Both the LLM and the embedding model are accessed through the free tiers of hosted providers, via API. Providers must be switchable through configuration without changing RAG pipeline logic. Running models locally is out of scope.
- **Consequences:**
  - A provider abstraction is required for the LLM and the embeddings.
  - Free-tier rate limits and quotas must be handled gracefully (clear errors, retry and backoff, batched embedding during ingestion).
  - Document chunks and questions leave the machine. Each candidate provider's free-tier data-usage terms (e.g., whether data may be used for training) must be documented in Phase 3, and they are a selection criterion.
  - Changing the embedding model invalidates stored vectors, so the model ID must be stored with the vectors and re-indexing must be supported.
  - Free-tier terms change over time. This is a delivery risk that the provider abstraction mitigates.
  - API keys are required, even for free tiers, and are supplied through environment variables only.
  - Concrete providers will be selected in Phase 3, with Arabic quality measured on the golden set.

## D-011 — Conversation handling: independent questions, follow-up-ready design
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** In this release, each question is processed independently; earlier turns are not used for retrieval or generation. The design must allow follow-up support to be added later without rebuilding the pipeline.
- **Consequences (kept minimal, with no unused machinery):**
  - Conversation messages are persisted in order.
  - Query processing is a separate, replaceable stage, so a query-rewriting stage can be added later.
  - No conversation context is sent to the LLM in this release.

## D-012 — UI language: Arabic, right-to-left
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The user interface is in Arabic with right-to-left layout.
- **Consequence:** UI text is in Arabic, while code identifiers stay in English (D-008). The layout must handle mixed Arabic and Latin content (e.g., file names, numbers).

## D-013 — Local models: not in this release, design ready for them
- **Date:** 2026-11-13 · **Status:** Approved (amends D-010)
- **Decision:** No model is downloaded or run locally; all models are used through hosted free-tier APIs (D-010). The design must still allow a provider that runs on the owner's machine behind a local API to be added later, through the same provider-switching mechanism and without changing RAG pipeline logic.
- **Consequences:**
  - The provider abstraction must not assume hosted-only traits, e.g., a mandatory API key or a fixed remote endpoint. The endpoint URL, model name, and key must be configuration values.
  - No local-provider adapter is shipped in this release: it could not be tested without a downloaded model, and untested functionality must not be claimed (CLAUDE.md §5).
  - Phase 3 considers whether a widely supported API format (for example an OpenAI-compatible interface, which many hosted and local servers expose) would reduce a future local provider to a configuration change. This is a selection criterion, not a pre-made choice.
  - Switching to a local embedding model later requires re-indexing (see D-010).

## D-014 — Phased plan approved
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The 12-phase plan in `docs/planning/PHASE_0_DISCOVERY_AND_PLAN.md` §7 is approved, including adjustments T1–T6. Phase 0 is complete. Phase 1 (Requirements Analysis) was authorized to start.
- **Note:** Approving the plan does not pre-approve later phases (`EXECUTION_PROTOCOL.md` §2).

## D-015 — Integration policy: one pull request per approved phase
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** Work happens on the designated development branch. After the owner approves a phase, Claude opens a pull request into `main` containing that phase's work. The owner reviews and merges it. Claude does not push to `main` directly.
- **Note:** Phase 0 was approved in the same message that started Phase 1, and only one development branch is in use, so the first pull request will contain both Phase 0 and Phase 1. It will be opened once Phase 1 is approved.

## D-016 — Phase 1 (SRS) approved with amendments
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The owner approved `docs/01_SRS.md`, with the amendments recorded in D-017 to D-021. These were applied in SRS v1.0.

## D-017 — Target operating system: Windows
- **Date:** 2026-11-13 · **Status:** Approved (resolves P-004)
- **Decision:** The owner's machine runs Windows. Windows is the installation and acceptance platform.
- **Consequences:**
  - Avoid POSIX-only tooling in setup and run scripts.
  - Watch for Windows path, encoding, and file-locking behaviour.
  - Development happens in a Linux container, so Windows behaviour must be verified separately. A Windows CI runner is the proposed mechanism (NFR-OPS-04, P-008), plus the owner's final clean-install check.

## D-018 — File size limit and performance targets
- **Date:** 2026-11-13 · **Status:** Approved (resolves P-005)
- **Decision:**
  - The maximum upload size is 10 MB per file.
  - Answer latency must be acceptable for interactive use and improvable. The initial target is a median of 10 s or less and a 95th percentile of 20 s or less, re-baselined after the first measurement.
  - The quality targets in SRS §5.9 and the other initial numeric targets are approved as **initial targets**. They are re-baselined after the first measurement and change only with owner approval.

## D-019 — Document version management
- **Date:** 2026-11-13 · **Status:** Approved (resolves P-007, replacing the "delete and re-upload" proposal)
- **Decision:** Documents support linear version management:
  - upload a new version of an existing document;
  - view the version history;
  - restore (activate) an earlier version;
  - delete an individual non-active version.

  Exactly one version per document is active and retrievable. A new version becomes active only when it is `Ready`. Content identical to any existing version is rejected.
- **Scope impact (CLAUDE.md §7):**
  - Adds a document-version entity, version-aware retrieval filtering, atomic activation, and more UI and tests.
  - Moderate complexity, no extra cost.
  - Bounded: no branching, merging, or diffing (FR-VER-06).
- **Open design point (Phase 4):** whether inactive versions keep their vectors (FR-VER-07).

## D-020 — Automatic conversation titles
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** Each conversation gets an automatic title derived from its first question (FR-CONV-06).

## D-021 — Use-case specialization: fictional cloud clinic-management platform
- **Date:** 2026-11-13 · **Status:** Approved (resolves P-006)
- **Decision:**
  - The system is specialized for one use case: a help assistant answering from the official documentation of a fictional cloud platform for managing medical clinics.
  - Its intended users are the clinic administrators and staff who use the platform.
  - The specialization is applied through a configurable **domain profile** (assistant name, scope statement, intended users, welcome text, example questions). The core pipeline stays domain-agnostic (FR-DOM-01..04).
- **Rationale:**
  - It makes the project a concrete product rather than a generic demo, which is better for the portfolio.
  - Keeping domain specifics in configuration preserves maintainability and lets the system be re-targeted.
  - A fictional platform keeps answers out of LLMs' prior knowledge, so grounding can be measured.
  - Platform documentation (procedures, plans and limits, SLAs, release notes, privacy) mixes prose, tables, numbers, and dates, which exercises extraction, chunking, and retrieval.
- **Boundary:** The assistant gives no clinical or medical advice (CON-10).
- **Sample corpus (Phase 2):**
  - 5 Arabic documents, all authored in Markdown first so the reference text is known.
  - 2 are converted to PDF and 3 stay as Markdown.
  - A golden set of 40–60 questions.

## D-022 — Platform name: «ضفيرة» (Dafira)
- **Date:** 2026-11-13 · **Status:** Approved (confirmed by the owner at the Phase 2 review, D-024)
- **Context:** The owner set the naming criteria: technical identity, fitting the use case, not a common name, and inspired by a story from the history of software and technology. The owner delegated the choice to Claude.
- **Decision:** «ضفيرة» (*braid*). It is inspired by the hand-woven core rope memory that stored the Apollo Guidance Computer's software, where a wire through a magnetic core encoded 1 and a wire around it encoded 0. The name maps to weaving a clinic's strands into one reliable cord. Full rationale and sources: `docs/02_SAMPLE_CORPUS.md` §2.

## D-023 — Corpus PDF production: Chromium (Playwright) with the Amiri font
- **Date:** 2026-11-13 · **Status:** Approved (confirmed by the owner at the Phase 2 review, D-024)
- **Context:** The owner delegated the choice of Markdown-to-PDF tool, with justification.
- **Decision:** Markdown is converted to HTML with markdown-it, and then to PDF with headless Chromium via Playwright. The font is Amiri (SIL OFL 1.1) with kerning disabled. This is development tooling only (`tools/corpus/`).
- **Evidence:**
  - Measured against WeasyPrint and LibreOffice, each with the same six fonts (`docs/02_SAMPLE_CORPUS.md` §5). The LibreOffice comparison was corrected on 2026-11-13 to use the same fonts (D-026); the decision did not change.
  - It had the best text-layer quality: pdftotext letter error 0.1%, letter CER 1.9%, word recall 84%.
- **Consequences:**
  - The tooling needs Node.js; there is no runtime role.
  - The corpus PDF acceptance criterion is the letter-multiset error (§5.5).

## D-024 — Phase 2 approved; Phase 3 authorized
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The owner approved the Phase 2 deliverables, including the platform name (D-022) and the PDF tooling (D-023), and approved the Phase 3 summary (Technology Evaluation and Selection), authorizing its start.
- **Integration:** Per D-015, Phase 2 goes to `main` through its own pull request. Phase 3 commits are held back until that pull request is merged, so the two phases are not mixed.

## D-025 — Providers for the Phase 3 proof of concept
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** The owner approved these free-tier providers for the Phase 3 PoC:
  - **Google AI Studio (Gemini):** LLM and embeddings.
  - **Groq:** alternative LLM and LLM-as-judge candidate.
  - **Cohere:** multilingual embeddings.
  - **Mistral:** optional.

  **Jina Embeddings** was added as an embedding candidate at the owner's confirmation; the owner already has an account.
- **Notes:**
  - The owner will create the accounts in due course. Work that needs keys is prepared so it runs as soon as keys are entered, and it does not block the rest of Phase 3.
  - API keys are entered through a secure credential form; they are never sent in chat or stored in Git.
  - From the cloud development container, only Gemini's host is currently reachable. The others are blocked by the container's network policy (not by the providers) until a credential for that host is saved.
  - Free-tier data-usage terms (e.g., Gemini and Mistral free tiers may use data to improve models) are acceptable for the fictional corpus. They will be documented per provider as a selection criterion for real data.

## D-026 — Evaluation principle: evidence, not the development environment
- **Date:** 2026-11-13 · **Status:** Approved (owner instruction)
- **Context:** The owner objected that technology candidates must not be nominated, evaluated, or chosen on the basis of the cloud development environment Claude works in. They must be chosen on reliable information and sources and on known efficiency.
- **Decision:** Technology choices rest only on the following, in this order:
  1. **Project requirements**, including the **target environment**: the owner's Windows machine (D-017), single user, free hosted providers (D-010).
  2. **Authoritative sources:** official documentation, licenses, official pricing and data-usage terms, maintenance status, and recognised public benchmarks (e.g., MTEB/MMTEB for embeddings). Third-party aggregator sites are used only as leads, never as evidence.
  3. **Reproducible measurements on the project's own Arabic corpus and golden set**, with pinned versions, so the results do not depend on the machine they run on. Where a result can depend on the OS (e.g., native binaries), it is re-verified on Windows.
- **Never a criterion:** what happens to be installed, pre-installed, or reachable in the development container.
  - Container limitations affect only *how* a measurement is run: the missing access or tool is set up, or the measurement runs on the owner's machine.
  - A candidate that cannot be measured is reported as "not measured". It is not dropped.
- **Corrections made:**
  - The PDF-tool comparison in Phase 2 had tested LibreOffice with one font only, because of what was installed in the container. It was re-run with the same fonts as the other tools; the conclusion stands.
  - The rationale "Chromium was already available" was replaced with a portable, environment-independent property.
  - The provider shortlist (D-025) is a lead from web research. Each provider's free-tier limits and data terms will be verified on its official pages in Phase 3 before any decision.

## D-027 — User interface: server-rendered Jinja2 + HTMX
- **Date:** 2026-11-13 · **Status:** Approved (resolves P-012)
- **Decision:** The UI is server-rendered HTML with Jinja2 templates and HTMX for partial updates (e.g., processing status), in Arabic with a right-to-left layout. React SPA was the alternative considered (TECH-001 T-03).
- **Consequences:**
  - One language (Python) and one runtime; no Node.js is needed on the owner's machine.
  - The backend still exposes a documented JSON API, so the UI can be replaced later without changing the pipeline.

## D-028 — PDF text extraction: pdftotext (Poppler)
- **Date:** 2026-11-13 · **Status:** Approved
- **Decision:** PDF text is extracted with Poppler's `pdftotext`, invoked as a separate process.
- **Evidence:** TECH-001 T-06. All 57 evidence passages stay intact, and BM25 Hit@5 is 0.93, versus 52 intact and 0.81 for pypdfium2.
- **Consequences:**
  - Windows needs a separate installation step (a conda-forge Poppler build). The owner accepts this. The step is documented in the README and checked at start-up (FR-CFG-04).
  - Results are re-verified on Windows (NFR-OPS-04, P-011).
  - The extractor sits behind an interface, so it can be replaced.

---

## Pending decisions

| ID | Question | Resolve by |
|---|---|---|
| P-008 | Lightweight CI (GitHub Actions) for tests and linting, including a Windows runner (D-017) | Phase 5 |
| P-011 | NFR-LNG-02 (PDF extraction CER ≤ 2%) may need redefinition. The sample pricing PDFs measure 2.6–3.1% letter CER with pdftotext before cleaning, caused entirely by table reflow (`docs/02_SAMPLE_CORPUS.md` §7). The proposal will be based on Phase 3 measurements and needs owner approval. | Phase 3 |
| P-013 | Provider API keys for the embedding and LLM measurements (TECH-001 T-10, T-11, T-12) | Before Phase 3 can close |
| P-014 | Default embedding model (TECH-001 T-10): gemini-embedding-001 (recommended: sustainable free-tier terms) or Cohere embed-v5.0-pro (best measured; trial key capped at 1,000 calls/month and not for production) | Phase 3 approval |

Resolved: P-001 → D-009 · P-002 → D-011 · P-003 → D-012 · P-004 → D-017 · P-005 → D-018 · P-006 → D-021 · P-007 → D-019 · P-009 → D-014 · P-010 → D-015 · P-012 → D-027.
