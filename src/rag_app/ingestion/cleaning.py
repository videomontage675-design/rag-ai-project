"""Stage 3 · Clean extracted PDF text and turn it into blocks (FR-ING-07).

Rules come from measurements on the sample PDFs (CORPUS-001 §7):
- bidi control characters are removed;
- lines repeated on most pages (headers and footers) are removed;
- a space is restored between digits and Arabic letters (lost at bidi run boundaries);
- paragraphs that pdftotext wrapped across a blank line are joined again;
- a combining mark that pdftotext places before its letter at a word start ("ُيمنع") is moved
  after that letter ("يُمنع"); stray lines holding one isolated letter ("ُط") are dropped;
- numbered headings that pdftotext emits in visual order (".2مقارنة") are restored ("2. مقارنة")
  and become the section heading of the blocks that follow; the first short line is the title.
"""

from __future__ import annotations

import re
from collections import Counter

from rag_app.domain.models import Block, BlockKind, ExtractedDocument

BIDI_CONTROLS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩"), None)
_ARABIC_LETTER = "ء-ي"
_DIGIT_BEFORE_ARABIC = re.compile(rf"(?<=[0-9])(?=[{_ARABIC_LETTER}])")
_ARABIC_BEFORE_DIGIT = re.compile(rf"(?<=[{_ARABIC_LETTER}]{{2}})(?=[0-9])")
_INDIC_BEFORE_ARABIC = re.compile(rf"(?<=[\u0660-\u0669])(?=[{_ARABIC_LETTER}])")
_SPACES = re.compile(r"[ \t ]+")
_VISUAL_HEADING = re.compile(r"^\.\s*([0-9٠-٩]{1,2})\s*(\S.{0,78})$")
_LOGICAL_HEADING = re.compile(r"^([0-9٠-٩]{1,2})\.\s*(\S.{0,78})$")
_SENTENCE_END = (".", "؟", "?", "!", ":", "؛", "…")
_WRAP_MIN_CHARS = 60
_EDGE_LINES = 2
_TITLE_MAX_CHARS = 100
_STARTS_WITH_LETTER = re.compile(rf"[{_ARABIC_LETTER}A-Za-z]")
_MARKS = "\u064b-\u065f\u0670"
_ORPHAN_MARKS = re.compile(rf"(?<![\w{_MARKS}])([{_MARKS}]+)([{_ARABIC_LETTER}])")
_LONE_LETTER = re.compile(rf"^[{_MARKS}]*[{_ARABIC_LETTER}][{_MARKS}]*$")


def tidy_line(line: str) -> str:
    """Remove bidi controls and stray fragments, restore spacing and mark order."""
    line = line.translate(BIDI_CONTROLS)
    line = _DIGIT_BEFORE_ARABIC.sub(" ", line)
    line = _ARABIC_BEFORE_DIGIT.sub(" ", line)
    line = _INDIC_BEFORE_ARABIC.sub(" ", line)
    line = _ORPHAN_MARKS.sub(r"\2\1", line)
    line = _SPACES.sub(" ", line).strip()
    return "" if _LONE_LETTER.match(line) else line


def _signature(line: str) -> str:
    return re.sub(r"[0-9\u0660-\u0669]+", "#", line)


def _edges(lines: list[str]) -> list[str]:
    """First and last ``_EDGE_LINES`` non-empty lines: where headers and footers live."""
    content = [ln for ln in lines if ln]
    return content[:_EDGE_LINES] + content[-_EDGE_LINES:]


def repeated_lines(pages: list[list[str]]) -> set[str]:
    """Signatures (digits masked) of page-edge lines repeated on at least half of the pages.

    Only the first and last lines of each page are considered, so words that legitimately
    repeat in the body (e.g. table headers) are never removed.
    """
    if len(pages) < 2:
        return set()
    counts = Counter(sig for lines in pages for sig in {_signature(ln) for ln in _edges(lines)})
    threshold = max(2, (len(pages) + 1) // 2)
    return {sig for sig, n in counts.items() if n >= threshold}


def as_heading(text: str) -> str | None:
    """Return the heading in logical order if ``text`` is a numbered section heading.

    The title part must start with an Arabic letter, so values such as ``99.95%`` are not
    mistaken for headings.
    """
    for pattern in (_VISUAL_HEADING, _LOGICAL_HEADING):
        match = pattern.match(text)
        if match:
            title = match.group(2).strip()
            if _STARTS_WITH_LETTER.match(title) and not title.endswith(_SENTENCE_END):
                return f"{match.group(1)}. {title}"
    return None


def _items(pages: list[list[str]], boilerplate: set[str]) -> list[tuple[str, str, int]]:
    """Linear sequence of ("title" | "heading" | "para", text, page) items."""
    items: list[tuple[str, str, int]] = []
    title_seen = False
    for page_no, lines in enumerate(pages, start=1):
        edges = set(_edges(lines))
        paragraph: list[str] = []
        for line in [*lines, ""]:  # the trailing "" flushes the last paragraph of the page
            if not line or (line in edges and _signature(line) in boilerplate):
                if paragraph:
                    items.append(("para", " ".join(paragraph), page_no))
                    paragraph = []
                continue
            heading = as_heading(line)
            if heading is not None:
                if paragraph:
                    items.append(("para", " ".join(paragraph), page_no))
                    paragraph = []
                items.append(("heading", heading, page_no))
            elif not title_seen and len(line) <= _TITLE_MAX_CHARS:
                items.append(("title", line, page_no))
            else:
                paragraph.append(line)
            title_seen = True
    return items


def clean_pdf_pages(pages: list[str]) -> ExtractedDocument:
    """Turn raw pdftotext pages into blocks with heading paths and page numbers."""
    tidy = [[tidy_line(ln) for ln in page.splitlines()] for page in pages]
    items = _items(tidy, repeated_lines(tidy))

    # Re-join paragraphs that pdftotext split at a wrapped line (long, no sentence end).
    merged: list[tuple[str, str, int]] = []
    for kind, text, page in items:
        if kind == "para" and merged and merged[-1][0] == "para":
            _, prev, prev_page = merged[-1]
            if len(prev) >= _WRAP_MIN_CHARS and not prev.endswith(_SENTENCE_END):
                merged[-1] = ("para", f"{prev} {text}", prev_page)
                continue
        merged.append((kind, text, page))

    blocks: list[Block] = []
    title: str | None = None
    section: str | None = None
    for kind, text, page in merged:
        if kind == "title":
            title = text
        elif kind == "heading":
            section = text
        else:
            path = tuple(p for p in (title, section) if p)
            blocks.append(Block(text, BlockKind.PARAGRAPH, path, page))
    return ExtractedDocument(blocks=tuple(blocks), page_count=len(pages))
