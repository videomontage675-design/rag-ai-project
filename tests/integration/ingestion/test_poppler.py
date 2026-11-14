import shutil
from pathlib import Path

import pytest

from rag_app.core.errors import AppError, ErrorCode
from rag_app.ingestion.poppler import locate_poppler

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="Poppler not installed on this runner"
)
def test_locates_installed_poppler_and_reads_version() -> None:
    tools = locate_poppler()

    assert tools.pdftotext.exists()
    assert tools.version != "unknown"


def test_missing_poppler_folder_raises_poppler_missing(tmp_path: Path) -> None:
    with pytest.raises(AppError) as info:
        locate_poppler(tmp_path)

    assert info.value.code is ErrorCode.POPPLER_MISSING
