"""Command-line interface: ``rag check`` and ``rag serve`` (DESIGN-001 §11.3).

Run as ``uv run rag <command>`` or ``python -m rag_app <command>``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from rag_app.config.settings import Settings, load_settings, settings_path_from_env
from rag_app.core.errors import AppError
from rag_app.core.logging import configure_logging
from rag_app.services.diagnostics import CheckLevel, run_checks

_SYMBOL = {CheckLevel.OK: "✔", CheckLevel.WARN: "!", CheckLevel.FAIL: "✘"}


def _load(settings_file: Path | None) -> Settings:
    settings = load_settings(settings_file or settings_path_from_env())
    # .env sits next to the config folder (project root); existing variables win.
    load_dotenv(settings.base_dir.parent / ".env", override=False)
    return settings


def _cmd_check(settings: Settings) -> int:
    results = run_checks(settings)
    width = max(len(r.name) for r in results)
    for r in results:
        print(f" {_SYMBOL[r.level]} {r.level:<4}  {r.name:<{width}}  {r.detail}")
    failed = sum(r.level is CheckLevel.FAIL for r in results)
    print(f"\n{len(results)} checks, {failed} failed")
    return 1 if failed else 0


def _cmd_serve(settings: Settings) -> int:
    import uvicorn  # imported lazily: only the serve command needs the server

    from rag_app.web.app import create_app

    configure_logging(
        settings.logging.level, settings.logs_dir if settings.logging.to_file else None
    )
    uvicorn.run(
        create_app(settings), host=settings.server.host, port=settings.server.port, log_config=None
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run a command, and return the process exit code."""
    # Windows consoles and redirected output may not default to UTF-8; Arabic must print.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="rag", description="Dafira RAG assistant")
    parser.add_argument("--settings", type=Path, default=None, help="path to settings.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate configuration, data folder, database, Poppler, keys")
    sub.add_parser("serve", help="start the web app on 127.0.0.1")
    args = parser.parse_args(argv)

    try:
        settings = _load(args.settings)
    except AppError as exc:
        print(f"✘ {exc.code}: {exc.message_ar}", file=sys.stderr)
        return 2
    if args.command == "check":
        return _cmd_check(settings)
    return _cmd_serve(settings)
