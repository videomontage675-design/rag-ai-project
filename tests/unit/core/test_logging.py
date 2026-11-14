import json
import logging

import pytest

from rag_app.core.logging import JsonFormatter, request_id_var

pytestmark = pytest.mark.unit


def _format(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))


def test_json_formatter_outputs_event_and_extra_fields() -> None:
    record = logging.makeLogRecord(
        {
            "msg": "stage_completed",
            "levelname": "INFO",
            "name": "t",
            "stage": "chunk",
            "duration_ms": 4,
        }
    )

    payload = _format(record)

    assert payload["event"] == "stage_completed"
    assert payload["stage"] == "chunk"
    assert payload["duration_ms"] == 4


def test_json_formatter_includes_current_request_id() -> None:
    token = request_id_var.set("req-12345678")
    try:
        payload = _format(logging.makeLogRecord({"msg": "x", "levelname": "INFO", "name": "t"}))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "req-12345678"


def test_json_formatter_keeps_arabic_readable() -> None:
    line = JsonFormatter().format(
        logging.makeLogRecord({"msg": "x", "levelname": "INFO", "name": "t", "note": "مرحبا"})
    )

    assert "مرحبا" in line
