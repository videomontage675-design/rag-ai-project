"""Environment diagnostics behind ``rag check`` (FR-CFG-04): fail early with clear reasons."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum

from rag_app.config.domain_profile import load_domain_profile
from rag_app.config.settings import Settings
from rag_app.core.errors import AppError
from rag_app.ingestion.poppler import locate_poppler
from rag_app.storage.db import Database
from rag_app.storage.migrate import apply_migrations


class CheckLevel(StrEnum):
    """Result level of one diagnostic check."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of one check, with a short human-readable explanation."""

    name: str
    level: CheckLevel
    detail: str


def run_checks(settings: Settings) -> list[CheckResult]:
    """Run every start-up check and return all results (never stops at the first failure)."""
    return [
        _check_domain_profile(settings),
        _check_data_dir(settings),
        _check_database(settings),
        _check_poppler(settings),
        *_check_keys(settings),
    ]


def _check_domain_profile(settings: Settings) -> CheckResult:
    try:
        profile = load_domain_profile(settings.resolve(settings.domain_profile_file))
    except AppError as exc:
        return CheckResult("domain profile", CheckLevel.FAIL, exc.message_ar)
    return CheckResult("domain profile", CheckLevel.OK, profile.assistant_name)


def _check_data_dir(settings: Settings) -> CheckResult:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=settings.data_dir):
            pass
    except OSError as exc:
        return CheckResult("data folder", CheckLevel.FAIL, f"{settings.data_dir}: {exc}")
    return CheckResult("data folder", CheckLevel.OK, str(settings.data_dir))


def _check_database(settings: Settings) -> CheckResult:
    try:
        applied = apply_migrations(Database(settings.database_file))
    except Exception as exc:  # noqa: BLE001  (diagnostics report any failure, then continue)
        return CheckResult("database", CheckLevel.FAIL, f"{type(exc).__name__}: {exc}")
    note = f"applied {', '.join(applied)}" if applied else "schema up to date"
    return CheckResult("database", CheckLevel.OK, f"{settings.database_file} ({note})")


def _check_poppler(settings: Settings) -> CheckResult:
    bin_dir = (
        settings.resolve(settings.paths.poppler_bin_dir) if settings.paths.poppler_bin_dir else None
    )
    try:
        tools = locate_poppler(bin_dir)
    except AppError as exc:
        return CheckResult("poppler (pdftotext)", CheckLevel.FAIL, exc.message_ar)
    return CheckResult(
        "poppler (pdftotext)", CheckLevel.OK, f"{tools.version} at {tools.pdftotext}"
    )


def _check_keys(settings: Settings) -> list[CheckResult]:
    results = []
    roles = [
        ("embedding", settings.providers.embedding, CheckLevel.FAIL),
        ("chat", settings.providers.chat, CheckLevel.FAIL),
    ]
    if settings.providers.judge is not None:
        roles.append(("judge (evaluation only)", settings.providers.judge, CheckLevel.WARN))
    for role, provider, missing_level in roles:
        name = f"API key: {role}"
        if provider.api_key_env is None:
            results.append(CheckResult(name, CheckLevel.OK, "no key required (local provider)"))
        elif os.environ.get(provider.api_key_env):
            results.append(CheckResult(name, CheckLevel.OK, f"{provider.api_key_env} is set"))
        else:
            results.append(
                CheckResult(
                    name, missing_level, f"{provider.api_key_env} is not set (see .env.example)"
                )
            )
    return results
