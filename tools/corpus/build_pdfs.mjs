// Development-only tool: renders the Markdown sources of the sample corpus
// that are distributed as PDF (see data/sample_corpus/manifest.yaml) into
// text-based PDFs, using Chromium's print-to-PDF engine.
//
// Why Chromium: it shapes Arabic text with HarfBuzz, supports right-to-left
// layout through standard HTML/CSS, embeds fonts with Unicode mappings (so the
// PDF keeps an extractable text layer), and is how many real-world PDFs are
// produced ("print to PDF"). See docs/02_SAMPLE_CORPUS.md for the comparison.
//
// For each PDF it also writes the rendered plain text (document.body.innerText)
// to reference_text/, which verify_corpus.py uses to measure how faithfully
// text can be extracted back from the PDF.
//
// Usage (from tools/corpus):  npm ci && npm run build-pdfs

import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, existsSync } from "node:fs";
import { dirname, join, resolve, basename } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import MarkdownIt from "markdown-it";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const corpusDir = resolve(here, "../../data/sample_corpus");
// Font, alignment and OpenType features are configurable so alternatives can
// be measured with verify_corpus.py. Defaults are the measured best choice
// (Amiri, kerning off); see docs/02_SAMPLE_CORPUS.md, "PDF production".
const fontPkg = process.env.CORPUS_FONT_PKG || "amiri";
const textAlign = process.env.CORPUS_TEXT_ALIGN || "justify";
const fontFeatures = process.env.CORPUS_FONT_FEATURES || '"kern" 0';
const fontDir = resolve(here, "node_modules/@fontsource", fontPkg);
const fontFamily = JSON.parse(readFileSync(join(fontDir, "metadata.json"), "utf8")).family;

// The manifest is YAML; to avoid another dependency, the PDF jobs are read
// from it with a narrow pattern: a "source:" line followed by an
// "upload_file: pdf/..." line.
function pdfJobs() {
  const text = readFileSync(join(corpusDir, "manifest.yaml"), "utf8");
  const re = /source:\s*(\S+\.md)\s*\n\s*upload_file:\s*(pdf\/\S+\.pdf)/g;
  const jobs = [];
  for (const m of text.matchAll(re)) jobs.push({ source: m[1], target: m[2] });
  if (jobs.length === 0) throw new Error("No PDF jobs found in manifest.yaml");
  return jobs;
}

const md = new MarkdownIt({ html: false, linkify: false, typographer: false });

function htmlPage(title, bodyHtml) {
  const links = ["400.css", "700.css"]
    .filter((f) => existsSync(join(fontDir, f)))
    .map((f) => `<link rel="stylesheet" href="${pathToFileURL(join(fontDir, f)).href}">`)
    .join("\n");
  return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>${title}</title>
${links}
<style>
  @page { size: A4; margin: 22mm 18mm 20mm 18mm; }
  body { font-feature-settings: ${fontFeatures}; font-family: "${fontFamily}", serif; font-size: 12pt; line-height: 1.75; color: #111; }
  h1 { font-size: 20pt; margin: 0 0 8pt; }
  h2 { font-size: 15pt; margin: 18pt 0 6pt; border-bottom: 1px solid #999; padding-bottom: 2pt; }
  h3 { font-size: 13pt; margin: 12pt 0 4pt; }
  p, li { margin: 4pt 0; text-align: ${textAlign}; }
  table { border-collapse: collapse; width: 100%; margin: 8pt 0; page-break-inside: auto; }
  tr { page-break-inside: avoid; }
  th, td { border: 1px solid #777; padding: 4pt 6pt; vertical-align: top; text-align: right; }
  th { background: #eee; }
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`;
}

const footerTemplate = `
<div style="width:100%; font-size:8pt; color:#555; text-align:center; font-family:sans-serif;" dir="rtl">
  منصة ضفيرة — صفحة <span class="pageNumber"></span> من <span class="totalPages"></span>
</div>`;

async function main() {
  const jobs = pdfJobs();
  const workDir = mkdtempSync(join(tmpdir(), "dafira-pdf-"));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    for (const job of jobs) {
      const src = readFileSync(join(corpusDir, job.source), "utf8");
      const title = (src.match(/^#\s+(.+)$/m) || [null, basename(job.source)])[1];
      const htmlPath = join(workDir, basename(job.source, ".md") + ".html");
      writeFileSync(htmlPath, htmlPage(title, md.render(src)), "utf8");

      await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
      await page.evaluate(() => document.fonts.ready);
      const fontOk = await page.evaluate((fam) => document.fonts.check(`12pt "${fam}"`, "ضفيرة"), fontFamily);
      if (!fontOk) throw new Error(`Arabic font not loaded for ${job.source}`);

      const outPdf = join(corpusDir, job.target);
      mkdirSync(dirname(outPdf), { recursive: true });
      await page.pdf({
        path: outPdf,
        format: "A4",
        printBackground: true,
        displayHeaderFooter: true,
        headerTemplate: "<div></div>",
        footerTemplate,
        margin: { top: "22mm", bottom: "20mm", left: "18mm", right: "18mm" },
      });

      const refText = await page.evaluate(() => document.body.innerText);
      const refPath = join(corpusDir, "reference_text", basename(job.target, ".pdf") + ".txt");
      mkdirSync(dirname(refPath), { recursive: true });
      writeFileSync(refPath, refText, "utf8");
      console.log(`built ${job.target}  [${fontFamily}, ${textAlign}]  (reference text: ${refText.length} chars)`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
