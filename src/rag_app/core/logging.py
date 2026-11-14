"""Structured JSON logging with per-request correlation identifiers.

Log *events*, not sentences: ``logger.info("stage_completed", extra={"stage": "chunk"})``.
Document text, questions, answers, and API keys must never be logged (STD-001 §8).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, ClassVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects (UTF-8, Arabic kept readable)."""

    reserved: ClassVar[frozenset[str]] = _STANDARD_ATTRS

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record, its ``extra`` fields, and the current request id."""
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        payload.update(
            {key: value for key, value in vars(record).items() if key not in self.reserved}
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure the root logger: JSON to stderr, and to a rotating file when ``log_dir`` is set.

    Calling it again replaces earlier handlers, so tests and the CLI can reconfigure safely.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = JsonFormatter()
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    root.setLevel(level.upper())
