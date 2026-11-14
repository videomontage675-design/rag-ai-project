"""Stage 2 · Extract Markdown into blocks with heading paths (FR-ING-06, T-07).

Structure comes from the Markdown itself: headings build the path, paragraphs and list items
become blocks, and every table row becomes one block (rows are never split, FR-ING-09).
Images are dropped; link text is kept.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.token import Token

from rag_app.domain.models import Block, BlockKind, ExtractedDocument

_MD = MarkdownIt("commonmark").enable("table")


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
    return " ".join("".join(parts).split())


def extract_markdown(text: str) -> ExtractedDocument:
    """Parse Markdown ``text`` into ordered blocks with their full heading path."""
    tokens = _MD.parse(text)
    headings: list[tuple[int, str]] = []
    blocks: list[Block] = []
    in_list_item = 0
    row: list[str] | None = None
    pending_heading_level: int | None = None

    def path() -> tuple[str, ...]:
        return tuple(title for _, title in headings)

    for token in tokens:
        if token.type == "heading_open":
            pending_heading_level = int(token.tag[1])
        elif token.type == "inline" and pending_heading_level is not None:
            level = pending_heading_level
            headings = [(lvl, title) for lvl, title in headings if lvl < level]
            headings.append((level, _inline_text(token)))
            pending_heading_level = None
        elif token.type == "list_item_open":
            in_list_item += 1
        elif token.type == "list_item_close":
            in_list_item -= 1
        elif token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(_inline_text(token))
        elif token.type == "tr_close" and row is not None:
            if any(cell for cell in row):
                blocks.append(Block(" | ".join(row), BlockKind.TABLE_ROW, path()))
            row = None
        elif token.type == "inline":
            content = _inline_text(token)
            if content:
                kind = BlockKind.LIST_ITEM if in_list_item else BlockKind.PARAGRAPH
                blocks.append(Block(content, kind, path()))
        elif token.type in {"fence", "code_block"} and token.content.strip():
            blocks.append(Block(token.content.strip(), BlockKind.PARAGRAPH, path()))
    return ExtractedDocument(blocks=tuple(blocks), page_count=None)
