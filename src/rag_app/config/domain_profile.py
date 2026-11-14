"""The domain profile: all use-case wording, kept out of the domain-agnostic core (FR-DOM-01)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_app.core.errors import AppError, ErrorCode


class DomainProfile(BaseModel):
    """Assistant identity and scope for one use case (D-021)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assistant_name: str = Field(min_length=1)
    platform_name: str = Field(min_length=1)
    scope_statement: str = Field(min_length=1)
    intended_users: str = Field(min_length=1)
    welcome_text: str = Field(min_length=1)
    example_questions: tuple[str, ...] = Field(default=(), max_length=10)
    insufficient_information_message: str = Field(min_length=1)


def load_domain_profile(path: Path) -> DomainProfile:
    """Load and validate a domain profile TOML file.

    Raises:
        AppError: ``CONFIG_INVALID`` when the file is missing or invalid.
    """
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        return DomainProfile.model_validate(raw)
    except FileNotFoundError as exc:
        raise AppError(
            ErrorCode.CONFIG_INVALID, reason=f"domain profile not found: {path}"
        ) from exc
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise AppError(
            ErrorCode.CONFIG_INVALID, reason=f"invalid domain profile {path}: {exc}"
        ) from exc
