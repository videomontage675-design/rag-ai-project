# Changelog

All notable changes, one section per phase. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (`0.y.z` until delivery).

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
