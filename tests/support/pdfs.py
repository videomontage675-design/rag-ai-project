"""Tiny hand-built PDFs for failure-path tests (no binary fixtures in Git).

They cover what FR-DOC-03 and DESIGN-001 §7 require the extractor to reject: a PDF without
a text layer (as a scanned PDF looks to pdftotext), a password-protected PDF, and a corrupt one.
"""

from __future__ import annotations

from pathlib import Path


def _pdf(objects: list[bytes], trailer_extra: bytes = b"") -> bytes:
    """Assemble numbered objects into a PDF with a correct cross-reference table."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R %s>>\n" % (len(objects) + 1, trailer_extra)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


_CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
_PAGES = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
_PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>"
_LINE = b"0 0 m 100 100 l S"  # draws a line: the page has content but no text
_DRAWING = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(_LINE), _LINE)


def blank_pdf() -> bytes:
    """A valid one-page PDF that contains only a drawing: no text layer."""
    return _pdf([_CATALOG, _PAGES, _PAGE, _DRAWING])


def encrypted_pdf() -> bytes:
    """A PDF whose standard security handler requires a user password."""
    key = b"<" + b"11" * 32 + b">"
    encrypt = b"<< /Filter /Standard /V 1 /R 2 /O " + key + b" /U " + key + b" /P -4 >>"
    return _pdf(
        [_CATALOG, _PAGES, _PAGE, _DRAWING, encrypt],
        trailer_extra=b"/Encrypt 5 0 R /ID [<00112233445566778899aabbccddeeff> "
        b"<00112233445566778899aabbccddeeff>] ",
    )


def corrupt_pdf() -> bytes:
    """Starts like a PDF but has no readable structure."""
    return b"%PDF-1.7\n" + b"\x00\x01garbage" * 50


def write(path: Path, data: bytes) -> Path:
    """Write ``data`` to ``path`` and return the path."""
    path.write_bytes(data)
    return path
