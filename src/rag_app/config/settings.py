"""Application settings loaded from ``config/settings.toml`` and validated at start-up.

Secrets are never stored here: provider entries only name the environment variable that holds
the key (``api_key_env``). Relative paths are resolved against the settings file's folder, so
the app behaves the same whatever the current directory is (Windows shortcuts, services).
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from rag_app.core.errors import AppError, ErrorCode

SETTINGS_ENV_VAR = "RAG_SETTINGS_FILE"
DEFAULT_SETTINGS_FILE = Path("config") / "settings.toml"


class _Strict(BaseModel):
    """Base for settings sections: unknown keys are errors (typos must not pass silently)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerSettings(_Strict):
    """HTTP server binding. Loopback only by default (NFR-SEC-01)."""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allow_non_local: bool = False

    @model_validator(mode="after")
    def _loopback_only(self) -> Self:
        if self.allow_non_local:
            return self
        try:
            is_loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            is_loopback = self.host == "localhost"
        if not is_loopback:
            msg = (
                f"server.host={self.host!r} is not a loopback address; the app has no "
                "authentication and must stay on this machine (NFR-SEC-01)"
            )
            raise ValueError(msg)
        return self


class PathSettings(_Strict):
    """Where runtime data lives and where Poppler is installed."""

    data_dir: Path = Path("../app_data")
    poppler_bin_dir: Path | None = None


class LimitSettings(_Strict):
    """Input limits (D-018, NFR-PRF-04/06)."""

    max_upload_mb: int = Field(default=10, ge=1, le=100)
    max_question_chars: int = Field(default=1000, ge=10, le=10_000)


class RagSettings(_Strict):
    """Retrieval and context parameters; initial values from DD-06, tuned in Phases 8–9."""

    chunk_chars: int = Field(default=800, ge=100)
    chunk_overlap: int = Field(default=150, ge=0)
    retrieve_k: int = Field(default=8, ge=1, le=50)
    context_max_passages: int = Field(default=5, ge=1, le=20)
    context_max_chars: int = Field(default=6000, ge=500)
    relevance_threshold: float = Field(default=0.60, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.chunk_overlap >= self.chunk_chars:
            msg = "rag.chunk_overlap must be smaller than rag.chunk_chars"
            raise ValueError(msg)
        if self.context_max_passages > self.retrieve_k:
            msg = "rag.context_max_passages cannot exceed rag.retrieve_k"
            raise ValueError(msg)
        return self


class ProviderSettings(_Strict):
    """One OpenAI-compatible endpoint (T-13). ``api_key_env`` names a variable, never a key."""

    base_url: str
    model: str
    api_key_env: str | None = None
    fallback_model: str | None = None
    batch_size: int = Field(default=20, ge=1, le=256)
    min_seconds_between_batches: float = Field(default=0.0, ge=0.0)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _https_or_local(cls, value: str) -> str:
        if value.startswith("https://") or value.startswith(
            ("http://127.0.0.1", "http://localhost")
        ):
            return value.rstrip("/")
        msg = "base_url must use https (or http on localhost for a local model server, D-013)"
        raise ValueError(msg)


class ProvidersSettings(_Strict):
    """Model providers: embeddings and chat are required; the judge is evaluation-only."""

    embedding: ProviderSettings
    chat: ProviderSettings
    judge: ProviderSettings | None = None


class LoggingSettings(_Strict):
    """Logging level and whether logs are also written to the data folder."""

    level: str = "INFO"
    to_file: bool = True


class Settings(_Strict):
    """All application settings. Construct with :func:`load_settings`."""

    server: ServerSettings = ServerSettings()
    paths: PathSettings = PathSettings()
    limits: LimitSettings = LimitSettings()
    rag: RagSettings = RagSettings()
    providers: ProvidersSettings
    logging: LoggingSettings = LoggingSettings()
    domain_profile_file: Path = Path("domain_profile.toml")
    source_file: Path = Field(default=Path(), exclude=True)

    @property
    def base_dir(self) -> Path:
        """Folder of the settings file; relative paths are resolved against it."""
        return self.source_file.parent

    def resolve(self, path: Path) -> Path:
        """Return ``path`` as an absolute path, relative paths taken from :attr:`base_dir`."""
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    @property
    def data_dir(self) -> Path:
        """Absolute data folder (database, uploads, logs)."""
        return self.resolve(self.paths.data_dir)

    @property
    def database_file(self) -> Path:
        """Absolute path of the SQLite database."""
        return self.data_dir / "rag.db"

    @property
    def uploads_dir(self) -> Path:
        """Absolute folder for original uploaded files."""
        return self.data_dir / "uploads"

    @property
    def logs_dir(self) -> Path:
        """Absolute folder for log files."""
        return self.data_dir / "logs"


def settings_path_from_env(default: Path = DEFAULT_SETTINGS_FILE) -> Path:
    """Return the settings file named by ``RAG_SETTINGS_FILE``, or ``default``."""
    return Path(os.environ.get(SETTINGS_ENV_VAR, str(default)))


def load_settings(path: Path | None = None) -> Settings:
    """Load and validate settings from a TOML file.

    Raises:
        AppError: ``CONFIG_INVALID`` when the file is missing, not valid TOML, or fails
            validation. The message names the problem without exposing secrets.
    """
    file = (path or settings_path_from_env()).resolve()
    try:
        with file.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, reason=f"settings file not found: {file}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, reason=f"invalid TOML in {file}: {exc}") from exc
    try:
        return Settings.model_validate({**raw, "source_file": file})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise AppError(ErrorCode.CONFIG_INVALID, reason=problems) from exc
