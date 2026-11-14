import pytest

from rag_app.ingestion.cleaning import as_heading, clean_pdf_pages, repeated_lines, tidy_line

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 59دولارًا", "59 دولارًا"),
        ("حتى  15مستخدمًا", "حتى 15 مستخدمًا"),
        ("كل ٦ساعات", "كل ٦ ساعات"),
        ("\u202bنص\u202c", "نص"),
    ],
)
def test_tidy_line_restores_spacing_and_removes_bidi(raw: str, expected: str) -> None:
    assert tidy_line(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (".2 مقارنة الخطط", "2. مقارنة الخطط"),  # pdftotext visual order
        (".١ الأدوار والمسؤوليات", "١. الأدوار والمسؤوليات"),
        ("3. الإضافات المدفوعة", "3. الإضافات المدفوعة"),
        ("99.95%", None),  # a value, not a heading
        ("1. هذه جملة كاملة تنتهي بنقطة.", None),
    ],
)
def test_as_heading(text: str, expected: str | None) -> None:
    assert as_heading(text) == expected


def test_repeated_lines_only_considers_page_edges() -> None:
    body = ["فقرة أولى", "الاحترافية", "فقرة ثانية"]  # a table word repeated in every page body
    pages = [["عنوان", "مقدمة", *body, "ختام", f"منصة ضفيرة — صفحة {n} من 3"] for n in (1, 2, 3)]

    found = repeated_lines(pages)

    assert found == {"منصة ضفيرة — صفحة # من #", "ختام", "عنوان", "مقدمة"}
    assert "الاحترافية" not in found


def test_clean_pdf_pages_builds_title_sections_and_rejoins_wrapped_lines() -> None:
    long_line = "تقدم ضفيرة ثلاث خطط اشتراك للعيادات الصغيرة والمتوسطة والكبيرة متعددة الفروع"
    footer = "منصة ضفيرة — صفحة {} من 2"
    page1 = f"الخطط والأسعار\n\n .1نظرة عامة\n{long_line}\n\nوتشمل الضرائب.\n\n{footer.format(1)}"
    page2 = f" .2مقارنة الخطط\nالأساسية\n\n{footer.format(2)}"

    doc = clean_pdf_pages([page1, page2])

    assert doc.page_count == 2
    texts = [(b.heading_path, b.text, b.page) for b in doc.blocks]
    assert texts[0] == (("الخطط والأسعار", "1. نظرة عامة"), f"{long_line} وتشمل الضرائب.", 1)
    assert texts[1] == (("الخطط والأسعار", "2. مقارنة الخطط"), "الأساسية", 2)
    assert not any("صفحة" in b.text for b in doc.blocks)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("عندها ُيمنع رفع", "عندها يُمنع رفع"),  # mark moved after its letter
        ("ُتشفَّر البيانات", "تُشفَّر البيانات"),
        ("وُيحتسب", "وُيحتسب"),  # mark after a letter is attached to it: left unchanged
        ("ُط", ""),  # isolated letter fragment
        ("و", ""),
        ("أ.", "أ."),  # not a lone letter: kept
    ],
)
def test_tidy_line_repairs_mark_order_and_drops_fragments(raw: str, expected: str) -> None:
    assert tidy_line(raw) == expected
