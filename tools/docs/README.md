# Documentation tooling (development only)

`check_mermaid.mjs` renders every Mermaid diagram found in the given Markdown
files with **Mermaid 11 and Mermaid 12** in headless Chromium and fails if any
diagram does not render. Two major versions are used because the Mermaid
version GitHub uses is not published; a diagram that renders in both is very
likely to render on GitHub.

```bash
cd tools/docs
npm ci
node check_mermaid.mjs ../../docs/*.md
```

Add `--png <folder>` to also write a PNG preview of each diagram (rendered with Mermaid 12).
