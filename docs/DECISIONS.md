# Decision Log

This log records decisions explicitly approved by the project owner. Each decision is also reflected in the relevant reference document (`docs/PROJECT_BRIEF.md`, `docs/EXECUTION_PROTOCOL.md`, or `CLAUDE.md`). Changes to an approved decision follow the change-management procedure in `docs/EXECUTION_PROTOCOL.md` §8.

Status values: **Approved** (decided by the owner) · **Pending** (open, with the phase by which it must be resolved).

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
- **Date:** 2026-11-13 · **Status:** Approved
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
- **Consequence:** Installation must work from a clean environment on that machine. Its specifications (OS, RAM, GPU) are still pending (P-004).

## D-006 — Users: 15–30, no authentication
- **Date:** 2026-11-13 · **Status:** Approved
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

---

## Pending decisions

| ID | Question | Resolve by |
|---|---|---|
| P-001 | Data ownership without authentication: one shared knowledge base or per-user ones? How are conversation histories separated? Who may delete documents? | Phase 1 |
| P-002 | Conversation nature: independent questions, or context-dependent follow-ups (needs query rewriting)? | Phase 1 |
| P-003 | UI language (Arabic RTL recommended, given Arabic users and content) | Phase 1 |
| P-004 | Specifications of the owner's machine (OS, RAM, GPU), which determine whether local models are feasible | Phase 3 (preferably Phase 1) |
| P-005 | Quantitative non-functional targets (latency, maximum file size, number of documents) | Phase 1 |
| P-006 | Topic of the sample corpus (a fictional but realistic domain is recommended) | Phase 2 |
| P-007 | Re-upload and update semantics (content-hash deduplication recommended) | Phase 1 |
| P-008 | Lightweight CI (GitHub Actions) for tests and linting | Phase 5 |
| P-009 | Approval of the revised phase plan (T1–T6 in the Phase 0 report) | Before Phase 1 |
