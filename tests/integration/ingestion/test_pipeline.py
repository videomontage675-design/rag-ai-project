from __future__ import annotations

from pathlib import Path

import pytest

from rag_app.config.settings import RagSettings
from rag_app.core.errors import AppError, ErrorCode
from rag_app.domain.models import DocumentFormat, ProcessingStage
from rag_app.ingestion.pipeline import process_file
from rag_app.ingestion.poppler import PopplerTools

pytestmark = pytest.mark.integration


def _no_poppler() -> PopplerTools:
    raise AssertionError("Markdown must not need Poppler")


def test_markdown_file_goes_through_stages_in_order(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text("# دليل\n\n## المواعيد\n\nيُنشأ الموعد من التقويم.\n", encoding="utf-8")
    stages: list[ProcessingStage] = []

    result = process_file(
        path, DocumentFormat.MARKDOWN, RagSettings(), poppler=_no_poppler, on_stage=stages.append
    )

    assert stages == [ProcessingStage.EXTRACTING, ProcessingStage.CHUNKING]
    assert result.page_count is None
    (chunk,) = result.chunks
    assert chunk.heading_path == "دليل › المواعيد"
    assert chunk.text_original == "يُنشأ الموعد من التقويم."
    assert chunk.text_normalized == "ينشأ الموعد من التقويم."


def test_markdown_with_only_headings_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("# عنوان فقط\n\n## قسم\n", encoding="utf-8")

    with pytest.raises(AppError) as info:
        process_file(path, DocumentFormat.MARKDOWN, RagSettings(), poppler=_no_poppler)

    assert info.value.code is ErrorCode.EMPTY_FILE


def test_a_stage_callback_can_cancel_processing(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text("نص", encoding="utf-8")

    class CancelledError(Exception):
        pass

    def cancel(stage: ProcessingStage) -> None:
        if stage is ProcessingStage.CHUNKING:
            raise CancelledError

    with pytest.raises(CancelledError):
        process_file(
            path, DocumentFormat.MARKDOWN, RagSettings(), poppler=_no_poppler, on_stage=cancel
        )
