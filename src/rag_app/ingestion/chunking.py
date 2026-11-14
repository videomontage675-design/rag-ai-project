"""Stage 4 · Split blocks into chunks that respect document structure (FR-ING-09/10, DD-06).

- A chunk never mixes two sections; each carries its section's **full heading path**
  (Phase 3 finding T-11 #6: a chunk without its parent heading loses its meaning).
- Blocks (paragraphs, list items, table rows) are kept whole; only a block longer than the
  target is split, at sentence and then word boundaries.
- Consecutive chunks of a section overlap by whole blocks up to ``overlap_chars``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby

from rag_app.domain.models import Block, ChunkDraft

PATH_SEPARATOR = " › "
_SENTENCE = re.compile(r"(?<=[.؟?!؛])\s+")


@dataclass(frozen=True, slots=True)
class _Piece:
    text: str
    page: int | None
    start: int


def _split_long(text: str, limit: int) -> list[str]:
    """Split text longer than ``limit`` at sentence, then word boundaries."""
    out: list[str] = []
    current = ""
    for unit in _SENTENCE.split(text):
        words = [unit] if len(unit) <= limit else unit.split()
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= limit or not current:
                current = candidate
            else:
                out.append(current)
                current = word
    if current:
        out.append(current)
    return out


def _pieces(blocks: Sequence[Block], limit: int, offset: int) -> tuple[list[_Piece], int]:
    pieces: list[_Piece] = []
    for block in blocks:
        for part in _split_long(block.text, limit) if len(block.text) > limit else [block.text]:
            pieces.append(_Piece(part, block.page, offset))
            offset += len(part) + 1
    return pieces, offset


def _windows(pieces: list[_Piece], size: int, overlap: int) -> Iterator[list[_Piece]]:
    start = 0
    while start < len(pieces):
        end, length = start, 0
        while end < len(pieces) and (end == start or length + len(pieces[end].text) + 1 <= size):
            length += len(pieces[end].text) + 1
            end += 1
        yield pieces[start:end]
        if end >= len(pieces):
            return
        back, carried = end, 0
        while back - 1 > start and carried + len(pieces[back - 1].text) + 1 <= overlap:
            back -= 1
            carried += len(pieces[back].text) + 1
        start = back


def chunk_blocks(
    blocks: Sequence[Block],
    *,
    size: int,
    overlap: int,
    normalize: Callable[[str], str],
) -> list[ChunkDraft]:
    """Build chunks from ``blocks``; ``normalize`` produces the searchable text of each chunk."""
    chunks: list[ChunkDraft] = []
    offset = 0
    for path, group in groupby(blocks, key=lambda b: b.heading_path):
        pieces, offset = _pieces(list(group), size, offset)
        heading = PATH_SEPARATOR.join(path)
        for window in _windows(pieces, size, overlap):
            text = "\n".join(p.text for p in window)
            pages = [p.page for p in window if p.page is not None]
            chunks.append(
                ChunkDraft(
                    seq=len(chunks),
                    heading_path=heading,
                    text_original=text,
                    text_normalized=normalize(text),
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    char_start=window[0].start,
                    char_end=window[-1].start + len(window[-1].text),
                )
            )
    return chunks
