import pytest

from rag_app.core.errors import CATALOG, AppError, ErrorCode

pytestmark = pytest.mark.unit


def test_catalog_covers_every_error_code() -> None:
    assert set(CATALOG) == set(ErrorCode)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_catalog_entry_has_arabic_message_and_http_error_status(code: ErrorCode) -> None:
    spec = CATALOG[code]

    assert 400 <= spec.http_status <= 599
    assert any("؀" <= ch <= "ۿ" for ch in spec.message_ar)


def test_app_error_fills_message_placeholders() -> None:
    error = AppError(ErrorCode.FILE_TOO_LARGE, limit_mb=10)

    assert "10" in error.message_ar
    assert error.http_status == 413


def test_app_error_with_missing_placeholder_still_returns_message() -> None:
    error = AppError(ErrorCode.DUPLICATE_CONTENT)

    assert error.message_ar == CATALOG[ErrorCode.DUPLICATE_CONTENT].message_ar


def test_app_error_keeps_details_as_independent_copy() -> None:
    details = {"field": "file"}
    error = AppError(ErrorCode.UNSUPPORTED_TYPE, details=details)
    details["field"] = "changed"

    assert error.details == {"field": "file"}
