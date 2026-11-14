"""Closed value sets of the domain (DESIGN-001 §5–§6). Stored as text in SQLite."""

from enum import StrEnum


class VersionStatus(StrEnum):
    """Lifecycle status of a document version (DESIGN-001 §6)."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"


class DocumentFormat(StrEnum):
    """Supported upload formats (D-003)."""

    PDF = "pdf"
    MARKDOWN = "markdown"


class AnswerOutcome(StrEnum):
    """Outcome of answering a question (FR-VAL-05)."""

    ANSWERED = "answered"
    ANSWERED_UNVERIFIED = "answered_unverified"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    ERROR = "error"
