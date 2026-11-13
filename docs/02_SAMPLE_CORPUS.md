# Sample Corpus and Golden Set

| Item | Value |
|---|---|
| Document ID | CORPUS-001 |
| Phase | Phase 2: Sample Corpus and Evaluation Dataset |
| Status | **Approved** (D-024) |
| Date | 2026-11-13 |
| Requirements | SRS §4.10 (FR-EVAL), §4.12 (FR-DOM), §4.11 (FR-VER), NFR-LNG-02, NFR-QLT-* |
| Decisions | D-002, D-003, D-019, D-021, D-022, D-023 |

---

## 1. Purpose

Phase 2 produces the knowledge base the system will be developed and evaluated against, plus a golden set of questions with known answers and known supporting locations. Without these, Phase 3 could not compare technologies on evidence, and later phases could not measure retrieval and answer quality objectively (CLAUDE.md §5).

Deliverables:

| Deliverable | Path |
|---|---|
| Five Arabic documents, plus a second version of one of them (Markdown reference sources) | `data/sample_corpus/source/` |
| PDF renditions of three document versions | `data/sample_corpus/pdf/` |
| Corpus manifest (documents, versions, states, ingestion sequence) | `data/sample_corpus/manifest.yaml` |
| Cross-document fact registry | `data/sample_corpus/facts.yaml` |
| Golden set: 53 questions | `eval/golden_set.yaml` |
| Build and verification tooling (development only) | `tools/corpus/` |
| Verification results | `data/sample_corpus/verification_report.json` |

> All corpus content is **fictional**. See `data/sample_corpus/README.md`.

---

## 2. Platform Name: «ضفيرة» (Dafira)

The owner asked for a name with technical identity, fitting the use case, avoiding common names, and inspired by a story from the history of software and technology.

**Meaning:** «ضفيرة» means *braid*: strands woven together into one strong cord.

**The story:** The Apollo Guidance Computer, which guided the Apollo missions in the 1960s, stored its programs in **core rope memory**. The software was literally *woven by hand*, largely by women at Raytheon's plant in Waltham, Massachusetts. A copper wire threaded **through** a small magnetic core encoded a 1; a wire passed **around** it encoded a 0. Once woven, the program could not be corrupted, so it was extremely reliable. Engineers nicknamed it "LOL memory" ("little old ladies"), although historians debate how widely the term was used at the time. ([Science News](https://sciencenews.org/?p=3110578); [Wikipedia: Core rope memory](https://en.wikipedia.org/wiki/Core_rope_memory))

**Why it fits:**

| Aspect | Connection |
|---|---|
| The product | A clinic platform weaves the clinic's separate strands (appointments, records, billing, staff) into one cord. |
| Reliability | Medical records demand the durability and reliability that woven rope memory stood for. |
| Memory | The platform is, at its core, the clinic's memory. |
| Identity | An Arabic word with a technical story behind it, uncommon as a product name, short and easy to pronounce. |

**Uniqueness check:** A web search for "Dafira" clinic software on 2026-11-13 found no product with this name. The closest result was an unrelated, differently spelled business-software vendor.

**Possible later use (not decided):** The assistant in the domain profile (FR-DOM-01) could be named «خيط» (*thread*): an assistant that "follows the thread" from an answer back to its source. This will be decided when the domain profile is configured.

---

## 3. Documents

| ID | Title | Version(s) | Uploaded as | Words | Headings | Tables | What it exercises |
|---|---|---|---|---|---|---|---|
| D01 | دليل المستخدم لمنصة ضفيرة | v1 | Markdown | ~1,135 | 21 | 2 | Step-by-step procedures, deep heading hierarchy, roles, troubleshooting |
| D02 | الخطط والأسعار وحدود الاستخدام | v1, v2 | PDF | ~530 / ~632 | 9 / 10 | 2 / 3 | Wide comparison tables, prices and limits, **versioning** (v2 changes 4 values) |
| D03 | سياسة الدعم الفني واتفاقية مستوى الخدمة | v1 | Markdown | ~712 | 11 | 5 | Numeric tables, value ranges (service credits), business rules |
| D04 | ملاحظات إصدارات منصة ضفيرة | v1 | Markdown | ~428 | 19 | 0 | Dates, changes over time, repeated sub-headings |
| D05 | سياسة الخصوصية وأمن البيانات | v1 | PDF | ~572 | 11 | 1 | **Arabic-Indic digits** (٠–٩), retention periods, security controls |

The default corpus state (`d02_v2_active`) is: all five documents uploaded, then D02 replaced by its version 2 (`manifest.yaml` → `ingestion_sequence`).

### 3.1 Deliberate design features

| Feature | Where | Tests |
|---|---|---|
| Facts spread across documents | e.g., the attachment limit (D01, and its history in D04); 2FA (D01, D04, D05); DICOM (D01, D02, D04) | Multi-document retrieval and synthesis |
| Intentional version differences only | D02 v1 vs v2: Basic price 49→59, Basic users 3→5, Professional SMS 1,000→1,500, annual discount 15%→20% | Version-aware retrieval (FR-VER-02, FR-RET-04) |
| The current version also mentions old values | D02 v2 §9 change summary | Answering with the current value even when an old one is present |
| Arabic-Indic digits | D05 only | Digit normalization (FR-ING-08): questions use Western digits |
| Tables with wrapped cells | D02, D03 in PDF and Markdown | Table extraction and chunking (FR-ING-09) |
| Near-miss facts | Retention periods for several data types but not for SMS; "prices exclude taxes" without a rate; patient payment methods but not subscription payment methods | Refusal on unanswerable questions without false grounding |
| Repeated page footer in PDFs | «منصة ضفيرة — صفحة N من M» on every page | Header/footer cleaning (FR-ING-07) |
| Colloquial phrasing | Golden-set paraphrased questions | Retrieval robustness to wording |

### 3.2 Consistency control: fact registry

`facts.yaml` lists 24 facts that are stated in more than one document or are version-sensitive. For each, it gives the exact text that must appear in each document that states it (69 occurrences). The verification script fails if any edit breaks a fact. The only intentional differences are marked `versioned: true` (D02 v1 vs v2).

**Limitation:** The registry proves that each registered fact is stated consistently. It cannot prove that an unregistered statement does not contradict another. The documents were also cross-read for consistency while being written.

---

## 4. Golden Set

### 4.1 Composition

| Category | Count | Purpose |
|---|---|---|
| single_doc | 14 | Direct fact lookup in one document |
| numeric_table | 8 | Numbers and table cells, including mapping a value into a range (Q018) |
| paraphrased | 6 | Wording different from the source, including colloquial Arabic |
| multi_doc | 10 | Evidence from two or more sections or documents |
| version_sensitive | 5 | The correct answer depends on which D02 version is active (Q043 is unanswerable under v1) |
| unanswerable | 7 | In-domain questions the corpus does not answer, including 4 near-miss traps |
| out_of_scope | 3 | Medical or general-knowledge questions the assistant must not answer (CON-10) |
| **Total** | **53** | In the default state, 10 questions (18.9%) expect an insufficient-information response |

Nine questions cite evidence from two or more documents, and several others combine two sections of the same document.

### 4.2 Schema and evidence design

Each answerable question records `evidence` as a list of entries. Each entry gives the document (and version), the enclosing `##` section, and short **verbatim snippets** that occur in that section.

**Why snippets rather than chunk IDs:** Chunk boundaries do not exist yet; they depend on the chunking strategy chosen and tuned in later phases. A snippet-based label stays valid under any chunking. A retrieved chunk counts as relevant if it comes from the cited document version and contains all the snippets (after the system's own normalization). This makes Hit@K, Recall@K, and MRR (FR-EVAL-02) computable for any chunking strategy, without relabeling.

Version-sensitive questions use `by_state`, which gives the expected outcome, the reference answer, and the evidence for each corpus state.

### 4.3 Known limitations

- **Single author.** The same author wrote the documents and the questions, so questions may be easier than real users' questions. This is mitigated by paraphrased and colloquial questions, near-miss traps, and multi-document questions, but not eliminated.
- **Small sample.** With 43 answerable questions in the default state, a measured proportion has a 95% confidence interval of roughly ±10–15 percentage points. Metric differences smaller than that between two configurations are not meaningful. This affects how Phase 3 and Phase 8 interpret comparisons.
- **Small corpus.** The corpus has about 3,400 words across five documents, which will likely produce on the order of 50–150 chunks. Retrieval is therefore easier than in a large knowledge base. Adding distractor documents would increase difficulty; it is not planned and would need approval.

---

## 5. PDF Production (decision D-023)

### 5.1 Requirement
Two documents (D02 in both versions, and D05) must be **text-based PDFs** (D-003) rendered from the Markdown sources, so the reference text is known. The PDFs must have a correct Arabic text layer, and their layout should resemble real-world PDFs.

### 5.2 Method

The selection was based on measured behaviour and documented properties of each tool, **not** on what happened to be installed in the development environment (D-026).

Every candidate rendered the same three document versions. Text was then extracted with two independent extractors, poppler's `pdftotext` and `pypdf`, and compared with the reference text that the renderer itself produced (`reference_text/`). Three metrics were computed, after Unicode NFKC normalization (which folds presentation forms) and after removing bidi control characters, tashkeel, tatweel, and the page footer:

| Metric | Definition | What it detects |
|---|---|---|
| **Letter error** (letter-multiset error) | Order-insensitive difference in per-character counts (letters, digits, symbols) ÷ reference length | Wrong or missing characters: is the text layer itself correct? |
| **Letter CER** | Levenshtein distance between letter sequences, with whitespace and punctuation removed, ÷ reference length | Wrong characters **and** wrong order |
| **Word recall** | Share of reference words (punctuation and tashkeel removed) found intact | Words split by spurious spaces or merged with neighbours |

### 5.3 Results (mean over the 3 PDFs)

| Producer | Font | pdftotext letter error | pdftotext letter CER | pdftotext word recall | pypdf letter error | pypdf letter CER | pypdf word recall |
|---|---|---|---|---|---|---|---|
| **Chromium** | **Amiri** | 0.1% | 1.9% | 84.0% | 2.1% | 66.9% | 86.7% |
| Chromium | Noto Naskh Arabic | 0.0% | 3.8% | 23.8% | 51.5% | 69.9% | 15.2% |
| Chromium | Noto Sans Arabic | 0.4% | 5.6% | 33.1% | 53.2% | 69.6% | 13.5% |
| Chromium | IBM Plex Sans Arabic | 0.0% | 13.3% | 64.0% | 2.0% | 65.9% | 87.1% |
| Chromium | Tajawal | 0.9% | 7.9% | 77.1% | 2.9% | 66.4% | 87.1% |
| Chromium | Cairo | 0.4% | 12.7% | 65.4% | 2.4% | 66.0% | 87.4% |
| LibreOffice | Amiri | 0.4% | 12.0% | 85.9% | 0.9% | 29.0% | 66.4% |
| LibreOffice | Noto Naskh Arabic | 0.4% | 9.8% | 25.8% | 32.5% | 72.7% | 6.2% |
| LibreOffice | Noto Sans Arabic | 0.9% | 9.4% | 34.7% | 29.8% | 72.2% | 5.6% |
| LibreOffice | IBM Plex Sans Arabic | 0.3% | 13.4% | 64.9% | 1.4% | 19.1% | 71.8% |
| LibreOffice | Tajawal | 0.6% | 6.3% | 77.4% | 1.6% | 19.2% | 72.2% |
| LibreOffice | Cairo | 0.9% | 18.2% | 65.8% | 2.1% | 19.7% | 73.6% |
| LibreOffice | DejaVu Sans | 0.6% | 7.0% | 78.0% | 1.8% | 19.3% | 72.0% |
| WeasyPrint 69.0 | Amiri | 14.0% | 14.2% | 47.4% | 56.3% | 59.8% | 33.9% |
| WeasyPrint 69.0 | Noto Naskh Arabic | 42.0% | 54.6% | 5.5% | 51.3% | 57.4% | 12.8% |
| WeasyPrint 69.0 | IBM Plex Sans Arabic | 4.3% | 23.5% | 62.5% | 18.9% | 25.8% | 66.8% |
| WeasyPrint 69.0 | Tajawal | 6.8% | 23.3% | 69.5% | 35.2% | 42.0% | 52.6% |

Notes:
- The Chromium rows used right alignment and default OpenType features. Alignment (justified vs. right) made no measurable difference. Disabling kerning raised word recall for Amiri from 84.4% to 86.2%, so it is part of the final configuration.
- pypdf's high letter CER with Chromium output comes from extracting right-to-left lines in **visual** (reversed) word order. Its word recall is high, so the words themselves are correct.
- LibreOffice cannot use WOFF2 web fonts, so it was tested with the same six fonts installed as TTF system fonts, plus DejaVu Sans. Its best result (Tajawal: letter CER 6.3%; with Amiri: 12.0%) does not reach Chromium + Amiri. *Correction (2026-11-13): an earlier version of this table tested LibreOffice with DejaVu Sans only, because only that font was installed in the development container. That was an unfair comparison and has been fixed; the conclusion did not change.*
- **Not evaluated:**
  - Pandoc with LaTeX: it needs a multi-gigabyte TeX installation, and Arabic in LaTeX needs special packages; the installation cost was not justified once a good option had been measured.
  - ReportLab: it requires manual reshaping into visual order, which by construction yields a poor text layer.
  - wkhtmltopdf: no longer maintained.

### 5.4 Decision
**Markdown → HTML (markdown-it) → PDF with headless Chromium via Playwright, using the Amiri font (SIL OFL 1.1) with kerning disabled.**

Rationale:
- **Best measured result:** the lowest letter CER and the highest pdftotext word recall, with a correct text layer (0.1% letter error).
- **Correct rendering:** HarfBuzz shaping and native CSS right-to-left layout. The rendering was checked visually.
- **Portable:** Playwright downloads a pinned Chromium build with one command on Windows, macOS, and Linux, so the tool behaves the same on any machine.
- **Realistic:** "print to PDF" from a browser is a very common way real PDFs are produced.
- **Reproducible:** a pinned script (`tools/corpus/package-lock.json`).

Trade-offs:
- The tooling uses Node.js, while the application stack is undecided (Phase 3). It is development-only and has no runtime role.
- PDFs are not byte-for-byte reproducible because of creation timestamps; their text content is.

### 5.5 Acceptance criterion for corpus PDFs
The corpus acceptance criterion is: **the text layer is correct**. For each PDF, the pdftotext letter error must be ≤ 1% and every page must have extractable text. Order and spacing artifacts are reported, not failed, because they depend on the extractor and are handled by cleaning and chunking (§7).

---

## 6. Verification Results

`tools/corpus/verify_corpus.py`, run on 2026-11-13, reports **all checks passed**. The full output is in `data/sample_corpus/verification_report.json`.

| Check | Result |
|---|---|
| Fact registry | 24 facts and 69 occurrences, all found |
| Golden set schema and ids | 53 unique questions; all 7 categories present |
| Evidence | Every snippet found verbatim in its cited section and version |
| Insufficient-information share (default state) | 18.9% (target 15–25%) |
| PDF text layer | Every page has text. pdftotext letter error: 0.09% (D02 v1), 0.08% (D02 v2), 0.00% (D05) |

Final PDFs (Chromium + Amiri, kerning off):

| PDF | pdftotext letter CER | pdftotext word recall | pypdf letter error | pypdf word recall |
|---|---|---|---|---|
| 02_plans_pricing_v1 | 3.1% | 86.4% | 2.3% | 83.2% |
| 02_plans_pricing_v2 | 2.6% | 84.2% | 2.0% | 81.9% |
| 05_privacy_security | 0.2% | 86.9% | 1.8% | 95.1% |

The higher letter CER on D02 comes from its comparison table: cells that wrap onto two lines are read row by row, so text moves out of its cell.

---

## 7. Findings for Phase 3 (text extraction)

These observations come from real measurements and should drive the extractor evaluation in Phase 3:

1. **Extraction quality depends on producer, font, and extractor together.** With the same Chromium output, the two extractors differ drastically (word order, presentation forms). The extractor must be chosen by measurement on this corpus.
2. **Tables:** Line-by-line extraction breaks wrapped cells. Table-aware extraction, or chunking that keeps table rows together, needs evaluation (FR-ING-09).
3. **Bidi boundaries:** Spaces between digits or Latin terms and Arabic words are lost or misplaced (e.g., «59دولاراً», «٦ساعات», RPO/٦ order). Cleaning must re-insert boundaries between scripts and digit runs.
4. **Spurious spaces inside words**, mostly after «ر» before «ي» with Amiri (e.g., «السر يان»). Cleaning or normalization should be evaluated against this.
5. **Presentation forms:** pypdf emits some Arabic presentation-form characters (42 per document, e.g., lam-alef). NFKC folds them (FR-ING-04).
6. **Tanween order** («معالجاً» vs «معالجًا») and other diacritic-order differences. Normalization rules for retrieval must account for them (FR-ING-08).
7. **Page footer** on every PDF page: header/footer removal (FR-ING-07).

**Risk to NFR-LNG-02:** The SRS target is "CER ≤ 2% after normalization on the sample PDFs". The pricing PDFs measure 2.6–3.1% letter CER with pdftotext before any cleaning, entirely because of table reflow. The target may need to be redefined in Phase 3 based on measurements of the selected extractor and cleaning, for example by separating letter correctness from table-structure fidelity. Any change requires owner approval (pending item P-011).

---

## 8. Reproducing

See `tools/corpus/README.md`. In short:

```bash
cd tools/corpus
npm ci
npm run build-pdfs
```

```bash
cd tools/corpus
.venv/bin/python verify_corpus.py --json ../../data/sample_corpus/verification_report.json
```
