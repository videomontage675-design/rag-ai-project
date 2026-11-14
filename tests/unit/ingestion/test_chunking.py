import itertools

import pytest

from rag_app.domain.models import Block, BlockKind
from rag_app.ingestion.chunking import PATH_SEPARATOR, chunk_blocks

pytestmark = pytest.mark.unit


def _block(
    text: str, path: tuple[str, ...] = ("دليل", "قسم"), kind: BlockKind = BlockKind.PARAGRAPH
) -> Block:
    return Block(text, kind, path, 1)


def _chunk(blocks: list[Block], size: int = 100, overlap: int = 20) -> list:
    return chunk_blocks(blocks, size=size, overlap=overlap, normalize=str.upper)


def test_chunks_never_mix_sections_and_keep_full_heading_path() -> None:
    blocks = [
        _block("أ" * 30, ("دليل", "الإصدار 4.0", "تغييرات")),
        _block("ب" * 30, ("دليل", "الإصدار 4.1")),
    ]

    chunks = _chunk(blocks)

    assert [c.heading_path for c in chunks] == [
        PATH_SEPARATOR.join(("دليل", "الإصدار 4.0", "تغييرات")),
        PATH_SEPARATOR.join(("دليل", "الإصدار 4.1")),
    ]


def test_chunks_respect_size_and_overlap_by_whole_blocks() -> None:
    blocks = [_block(f"فقرة{i} " + "س" * 30) for i in range(6)]

    chunks = _chunk(blocks, size=100, overlap=40)

    assert all(len(c.text_original) <= 100 for c in chunks)
    assert len(chunks) > 1
    for previous, current in itertools.pairwise(chunks):
        assert current.text_original.splitlines()[0] in previous.text_original  # overlap


def test_table_rows_are_never_split() -> None:
    rows = [_block(f"صف {i} | قيمة {i}", kind=BlockKind.TABLE_ROW) for i in range(20)]

    chunks = _chunk(rows, size=60, overlap=0)

    for chunk in chunks:
        for line in chunk.text_original.splitlines():
            assert line.startswith("صف ") and " | قيمة " in line


def test_overlong_block_is_split_at_sentence_boundaries() -> None:
    text = " ".join(f"جملة رقم {i} تنتهي هنا." for i in range(20))

    chunks = _chunk([_block(text)], size=80, overlap=0)

    assert len(chunks) > 1
    assert all(len(c.text_original) <= 80 for c in chunks)
    assert "".join(c.text_original.replace(" ", "") for c in chunks) == text.replace(" ", "")


def test_normalized_text_and_offsets_are_filled() -> None:
    chunks = _chunk([_block("abc"), _block("def")], size=100)

    assert chunks[0].text_normalized == "ABC\nDEF"
    assert (chunks[0].char_start, chunks[0].char_end) == (0, 7)
    assert chunks[0].page_start == chunks[0].page_end == 1


def test_empty_input_gives_no_chunks() -> None:
    assert _chunk([]) == []
