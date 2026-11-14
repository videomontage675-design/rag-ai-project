"""Identifier generation (UUID4 strings), kept in one place so the format can change safely."""

import uuid


def new_id() -> str:
    """Return a new random identifier as a 36-character UUID string."""
    return str(uuid.uuid4())
