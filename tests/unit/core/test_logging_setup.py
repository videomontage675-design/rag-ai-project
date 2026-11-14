import json
import logging
from pathlib import Path

import pytest

from rag_app.core.logging import configure_logging

pytestmark = pytest.mark.unit


def test_configure_logging_writes_json_lines_to_utf8_file(tmp_path: Path) -> None:
    configure_logging("INFO", tmp_path / "logs")
    try:
        logging.getLogger("t").info("document_uploaded", extra={"version_id": "v1", "note": "عربي"})
        for handler in logging.getLogger().handlers:
            handler.flush()

        line = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    finally:
        configure_logging("WARNING", None)

    record = json.loads(line)
    assert record["event"] == "document_uploaded"
    assert record["version_id"] == "v1"
    assert record["note"] == "عربي"
