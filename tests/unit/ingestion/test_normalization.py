import pytest

from rag_app.ingestion.normalization import normalize_arabic

pytestmark = pytest.mark.unit


def test_folds_presentation_forms_and_removes_tashkeel_and_tatweel() -> None:
    assert normalize_arabic("\ufee0\ufedf ـمـعـالَجاً") == normalize_arabic("لل معالجا")


def test_unifies_arabic_indic_digits() -> None:
    assert normalize_arabic("مدة ٣٥ يوماً و ۱۲") == "مدة 35 يوما و 12"


def test_collapses_whitespace_and_bidi_controls() -> None:
    assert normalize_arabic("\u202b نص \n\n آخر \u202c") == "نص آخر"
