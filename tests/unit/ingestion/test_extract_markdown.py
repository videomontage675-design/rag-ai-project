import pytest

from rag_app.domain.models import BlockKind
from rag_app.ingestion.extract_markdown import extract_markdown

pytestmark = pytest.mark.unit

DOC = """# دليل

مقدمة **مهمة** عن [المنصة](https://example.com) ![شعار](logo.png)

## 1. المواعيد

### 1.1 الإنشاء

- خطوة أولى
- خطوة ثانية

## 2. الخطط

| البند | الأساسية |
|---|---|
| السعر | 59 دولاراً |
"""


def test_blocks_carry_full_heading_path_and_kinds() -> None:
    blocks = extract_markdown(DOC).blocks

    assert blocks[0].heading_path == ("دليل",)
    assert blocks[0].text == "مقدمة مهمة عن المنصة شعار".replace(" شعار", "")
    steps = [b for b in blocks if b.kind is BlockKind.LIST_ITEM]
    assert [b.text for b in steps] == ["خطوة أولى", "خطوة ثانية"]
    assert steps[0].heading_path == ("دليل", "1. المواعيد", "1.1 الإنشاء")


def test_each_table_row_is_one_block_under_its_section() -> None:
    rows = [b for b in extract_markdown(DOC).blocks if b.kind is BlockKind.TABLE_ROW]

    assert [r.text for r in rows] == ["البند | الأساسية", "السعر | 59 دولاراً"]
    assert rows[0].heading_path == ("دليل", "2. الخطط")


def test_heading_level_change_resets_deeper_levels() -> None:
    blocks = extract_markdown("# أ\n## ب\n### ج\nنص1\n## د\nنص2\n").blocks

    assert blocks[-1].heading_path == ("أ", "د")
