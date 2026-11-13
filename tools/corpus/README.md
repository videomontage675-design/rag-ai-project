# Corpus tooling (development only)

These tools build and verify the Arabic sample corpus in `data/sample_corpus/`
and the golden set in `eval/golden_set.yaml`. They are **not** part of the RAG
application and are not used at runtime.

| File | Purpose |
|---|---|
| `build_pdfs.mjs` | Renders the Markdown sources listed as PDF in `manifest.yaml` into text-based PDFs with Chromium (via Playwright) and the Amiri font, and writes the rendered plain text to `reference_text/`. |
| `verify_corpus.py` | Acceptance checks: fact registry, golden-set schema and evidence, and PDF text-layer quality. |
| `package.json` / `package-lock.json` | Pinned Node dependencies for `build_pdfs.mjs`. |
| `requirements.txt` | Pinned Python dependencies for `verify_corpus.py`. |

## Usage

Requirements: Node.js 22+, Python 3.11+, and poppler's `pdftotext`.

```bash
cd tools/corpus
npm ci
npx playwright install chromium
npm run build-pdfs
```

```bash
cd tools/corpus
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python verify_corpus.py --json ../../data/sample_corpus/verification_report.json
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`.
`npx playwright install chromium` is only needed where Playwright's
Chromium is not already installed.

Environment variables (`CORPUS_FONT_PKG`, `CORPUS_TEXT_ALIGN`,
`CORPUS_FONT_FEATURES`) override the font, alignment, and OpenType features.
They exist to reproduce the comparison in `docs/02_SAMPLE_CORPUS.md`; the
defaults are the selected configuration.

PDFs are not byte-for-byte reproducible (Chromium embeds a creation
timestamp), but their text content is.
