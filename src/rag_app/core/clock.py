"""Time helpers. All stored timestamps are timezone-aware UTC in ISO-8601 (STD-001 §5.3)."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with seconds precision."""
    return utc_now().isoformat(timespec="seconds")
