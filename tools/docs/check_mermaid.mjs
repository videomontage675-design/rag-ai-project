// Development-only: renders every ```mermaid block in the given Markdown files
// with two Mermaid major versions (11 and 12) in headless Chromium, and fails
// if any diagram does not render. Two versions are used because the version
// GitHub uses to render Markdown is not published; a diagram that renders in
// both is very likely to render there.
//
// Usage (from tools/docs):  npm ci && node check_mermaid.mjs ../../docs/*.md [--png out_dir]
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const pngIdx = args.indexOf("--png");
const pngDir = pngIdx >= 0 ? resolve(args[pngIdx + 1]) : null;
const files = args.filter((a, i) => !(pngIdx >= 0 && (i === pngIdx || i === pngIdx + 1)));
const versions = ["mermaid11", "mermaid12"];

const blocks = [];
for (const f of files) {
  const md = readFileSync(f, "utf8");
  let i = 0;
  for (const m of md.matchAll(/```mermaid\n([\s\S]*?)```/g)) blocks.push({ file: basename(f), n: ++i, code: m[1] });
}

const browser = await chromium.launch();
let failures = 0;
try {
  for (const v of versions) {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    await page.setContent("<html><body style='background:#fff'><div id='out'></div></body></html>");
    await page.addScriptTag({ path: join(here, "node_modules", v, "dist", "mermaid.min.js") });
    await page.evaluate(() => mermaid.initialize({ startOnLoad: false, securityLevel: "strict" }));
    for (const b of blocks) {
      const res = await page.evaluate(async ({ code, id }) => {
        try { const { svg } = await mermaid.render(id, code); document.getElementById("out").innerHTML = svg; return { ok: true }; }
        catch (e) { return { ok: false, err: String(e.message || e).slice(0, 300) }; }
      }, { code: b.code, id: `d${b.n}${v}` });
      if (!res.ok) { failures++; console.log(`FAIL [${v}] ${b.file} diagram #${b.n}: ${res.err}`); }
      else if (pngDir && v === "mermaid12") {
        mkdirSync(pngDir, { recursive: true });
        const el = await page.$("#out svg");
        writeFileSync(join(pngDir, `${b.file.replace(".md", "")}_${b.n}.png`), await el.screenshot());
      }
    }
    await page.close();
  }
} finally { await browser.close(); }
console.log(`${blocks.length} diagrams x ${versions.length} Mermaid versions: ${failures ? failures + " failure(s)" : "all rendered"}`);
process.exit(failures ? 1 : 0);
