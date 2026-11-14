import pytest

from rag_app.web.ui.format import arabic_count, datetime_ar, filesize

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "مستند واحد"),
        (2, "مستندان"),
        (3, "3 مستندات"),
        (10, "10 مستندات"),
        (11, "11 مستنداً"),
        (103, "103 مستندات"),
        (0, "0 مستنداً"),
    ],
)
def test_arabic_count_follows_number_agreement(n: int, expected: str) -> None:
    assert arabic_count(n, "مستند واحد", "مستندان", "مستندات", "مستنداً") == expected


@pytest.mark.parametrize(
    ("size", "expected"),
    [(57, "57 بايت"), (6_300, "6 كيلوبايت"), (75_776, "74 كيلوبايت"), (3_300_000, "3.1 ميجابايت")],
)
def test_filesize(size: int, expected: str) -> None:
    assert filesize(size) == expected


def test_datetime_ar_uses_arabic_month_names() -> None:
    text = datetime_ar("2026-09-01T12:00:00+00:00")

    assert "سبتمبر 2026" in text or "أغسطس 2026" in text  # local time zone may shift the day
    assert datetime_ar("not a date") == "not a date"
