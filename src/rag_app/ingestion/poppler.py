"""Locate the Poppler command-line tools used for PDF extraction (D-028).

Poppler is an external program, so its presence and version are checked explicitly and
reported by ``rag check`` instead of failing later in the middle of an upload.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rag_app.core.errors import AppError, ErrorCode

_VERSION = re.compile(r"version\s+(\d+(?:\.\d+)+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PopplerTools:
    """Absolute paths of the Poppler executables and the detected version."""

    pdftotext: Path
    pdfinfo: Path
    version: str


def _find(name: str, bin_dir: Path | None) -> Path | None:
    found = shutil.which(name, path=str(bin_dir)) if bin_dir is not None else shutil.which(name)
    return Path(found) if found else None


def locate_poppler(bin_dir: Path | None = None, timeout_seconds: float = 10.0) -> PopplerTools:
    """Find ``pdftotext`` and ``pdfinfo`` (in ``bin_dir`` or on PATH) and read their version.

    Raises:
        AppError: ``POPPLER_MISSING`` when either tool is missing or cannot be run.
    """
    pdftotext = _find("pdftotext", bin_dir)
    pdfinfo = _find("pdfinfo", bin_dir)
    if pdftotext is None or pdfinfo is None:
        raise AppError(
            ErrorCode.POPPLER_MISSING,
            details={"searched": str(bin_dir) if bin_dir else "PATH"},
        )
    try:
        result = subprocess.run(  # noqa: S603  (fixed argument list, no shell)
            [str(pdftotext), "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError(ErrorCode.POPPLER_MISSING, details={"error": str(exc)}) from exc
    match = _VERSION.search(result.stdout + result.stderr)
    return PopplerTools(pdftotext, pdfinfo, match.group(1) if match else "unknown")
