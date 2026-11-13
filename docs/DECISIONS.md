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

---

## Pending decisions

| ID | Question | Resolve by |
|---|---|---|
| P-004 | Operating system of the owner's machine (affects installation and run instructions) | Phase 1 |
| P-005 | Quantitative non-functional targets (latency, maximum file size, number of documents) | Phase 1 |
| P-006 | Topic of the sample corpus (a fictional but realistic domain is recommended) | Phase 2 |
| P-007 | Re-upload and update semantics (content-hash deduplication recommended) | Phase 1 |
| P-008 | Lightweight CI (GitHub Actions) for tests and linting | Phase 5 |

Resolved: P-001 → D-009 · P-002 → D-011 · P-003 → D-012 · P-009 → D-014 · P-010 → D-015.
