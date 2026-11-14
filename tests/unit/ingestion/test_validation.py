import pytest

from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import DocumentFormat
from rag_app.ingestion.validation import decode_markdown, detect_format, safe_display_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "head", "expected"),
    [
        ("guide.pdf", b"%PDF-1.7 ...", DocumentFormat.PDF),
        ("GUIDE.PDF", b"%PDF-1.4", DocumentFormat.PDF),
        ("notes.md", "# عنوان".encode(), DocumentFormat.MARKDOWN),
        ("notes.markdown", b"text", DocumentFormat.MARKDOWN),
    ],
)
def test_detect_format_accepts_matching_extension_and_content(
    name: str, head: bytes, expected: DocumentFormat
) -> None:
    assert detect_format(name, head) is expected


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("fake.pdf", b"# not a pdf"),  # renamed text file
        ("fake.md", b"%PDF-1.7"),  # PDF renamed to .md
        ("report.docx", b"PK\x03\x04"),  # unsupported format (D-003)
        ("noext", b"hello"),
    ],
)
def test_detect_format_rejects_mismatch_or_other_types(name: str, head: bytes) -> None:
    with pytest.raises(AppError) as info:
        detect_format(name, head)

    assert info.value.code is ErrorCode.UNSUPPORTED_TYPE


def test_detect_format_rejects_empty_file() -> None:
    with pytest.raises(AppError) as info:
        detect_format("a.md", b"")

    assert info.value.code is ErrorCode.EMPTY_FILE


def test_decode_markdown_accepts_utf8_with_bom() -> None:
    assert decode_markdown("\ufeff# مرحبا".encode()) == "# مرحبا"


@pytest.mark.parametrize("data", [b"\xff\xfe\x00broken", "نص\x00ثنائي".encode()])
def test_decode_markdown_rejects_invalid_utf8_or_nul(data: bytes) -> None:
    with pytest.raises(AppError) as info:
        decode_markdown(data)

    assert info.value.code is ErrorCode.INVALID_UTF8


def test_safe_display_name_strips_folders_and_extension() -> None:
    assert safe_display_name("C:\\Users\\x\\دليل المستخدم.pdf") == "دليل المستخدم"
    assert safe_display_name("../../etc/passwd.md") == "passwd"
