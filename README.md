# Dafira RAG Assistant

An Arabic question-answering assistant over a private document knowledge base. You upload
documents (text-based PDF and Markdown); it answers questions **only from those documents**,
shows the sources it used, and says so plainly when the documents do not contain the answer.

The initial deployment is a help assistant for «ضفيرة», a **fictional** cloud platform for
managing medical clinics. All use-case wording lives in `config/domain_profile.toml`; the core
is domain-agnostic.

> **Status:** Phase 5 (project foundation). The app starts and has a health endpoint, a status
> API, and an Arabic RTL welcome page. Uploading documents and asking questions arrive in
> Phases 6–10. The roadmap is in `docs/planning/PHASE_0_DISCOVERY_AND_PLAN.md`.

---

## Quick start on Windows (about 5 minutes)

**1. Install the prerequisites (once)**

| Tool | Why | How |
|---|---|---|
| **uv** | Installs Python 3.13 and the exact locked dependencies | PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| **Poppler** | Extracts text from PDFs (D-028) | Install the conda-forge `poppler` package, e.g. `conda install -c conda-forge poppler`. Then either add its `Library\bin` folder to `PATH` or set `paths.poppler_bin_dir` in `config/settings.toml` |
| **Git** | Gets the code | <https://git-scm.com/download/win> |

**2. Get the code and install**

```powershell
git clone https://github.com/videomontage675-design/rag-ai-project.git
cd rag-ai-project
uv sync
```

**3. Add your API keys**

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in `GEMINI_API_KEY` and `GROQ_API_KEY`. `COHERE_API_KEY` is only needed for evaluation.
`.env` is git-ignored and never committed.

**4. Check the setup, then start**

```powershell
uv run rag check
uv run rag serve
```

Open <http://127.0.0.1:8000>. The app listens **only on this computer**: it has no login, so
it refuses to start on a network address.

`rag check` reports each item as ✔ OK, ! WARN, or ✘ FAIL with the reason. Fix every FAIL
before `rag serve`.

---

## What leaves your computer

| Data | Sent to | When |
|---|---|---|
| Text of document chunks | Google Gemini API (embeddings) | When a document is processed |
| Your question | Google Gemini API (embeddings) | Every question |
| Your question plus the retrieved passages | Groq API (answer generation) | Every question that has relevant passages |
| Questions, answers, and passages of the golden set | Cohere API (judge) | Only when you run the offline evaluation |

These are **free tiers**. Google's free tier uses submitted content to improve its products,
and Groq's and Cohere's terms are linked in `docs/03_TECHNOLOGY_EVALUATION.md`. Do not upload
real patient data while using free tiers.

---

## Configuration

| File | Content | In Git |
|---|---|---|
| `config/settings.toml` | Server, data folder, limits, RAG parameters, providers and models | Yes |
| `config/domain_profile.toml` | Assistant name, scope, welcome text, example questions | Yes |
| `.env` | API key values | **Never** |

Runtime data (database, uploaded files, logs) goes to `app_data/` (configurable, git-ignored).
To use another settings file, set `RAG_SETTINGS_FILE` or pass `--settings`.

---

## For developers

```bash
uv sync                   # environment + dev tools
uv run pytest             # tests (network blocked)
uv run ruff check         # lint
uv run ruff format        # format
uv run mypy               # types (strict)
uv run lint-imports       # architecture layer rules
```

| Read this | To learn |
|---|---|
| [`docs/06_DEVELOPER_GUIDE.md`](docs/06_DEVELOPER_GUIDE.md) | Project structure, request flow, how the API works, how to add features, **where every document lives** |
| [`docs/05_ENGINEERING_STANDARDS.md`](docs/05_ENGINEERING_STANDARDS.md) | Binding coding, testing, Git, and writing standards |
| [`docs/04_ARCHITECTURE_AND_DESIGN.md`](docs/04_ARCHITECTURE_AND_DESIGN.md) | Architecture, data model, pipelines, API contract |
| [`docs/01_SRS.md`](docs/01_SRS.md) | Requirements |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every approved decision and its reasons |

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `✘ FAIL poppler (pdftotext)` | Poppler is not on `PATH`. Set `paths.poppler_bin_dir` to the folder that contains `pdftotext.exe` |
| `✘ FAIL API key: embedding` | `GEMINI_API_KEY` is missing in `.env` |
| `CONFIG_INVALID … server.host` | The host is not `127.0.0.1`. The app has no login, so it only runs locally |
| Arabic text shows as `?` in the terminal | Use Windows Terminal; the app forces UTF-8 output, but the old console may lack fonts |
