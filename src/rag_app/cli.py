"""Command-line interface: ``rag check``, ``rag serve``, and ``rag reindex`` (DESIGN-001 §11.3).

Run as ``uv run rag <command>`` or ``python -m rag_app <command>``.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from rag_app.config.settings import Settings, load_settings, settings_path_from_env
from rag_app.core.errors import AppError
from rag_app.core.logging import configure_logging
from rag_app.providers.factory import open_embedding_provider
from rag_app.providers.ports import ProviderError
from rag_app.providers.resilience import resilient
from rag_app.services.diagnostics import CheckLevel, run_checks
from rag_app.services.ingestion_worker import ingestion_retry_policy
from rag_app.services.reindex import ReindexService
from rag_app.storage.db import Database
from rag_app.storage.migrate import apply_migrations

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


def _cmd_reindex(settings: Settings) -> int:
    """Embed every ready version with the configured model (FR-CFG-05); app must be stopped."""
    cfg = settings.providers.embedding
    configure_logging(
        settings.logging.level, settings.logs_dir if settings.logging.to_file else None
    )
    db = Database(settings.database_file)
    apply_migrations(db)
    adapter = open_embedding_provider(cfg)
    embedder = resilient(
        adapter,
        retry=ingestion_retry_policy(settings),
        min_interval=cfg.min_seconds_between_batches,
        sleep=time.sleep,
    )
    service = ReindexService(db, embedder, batch_size=cfg.batch_size)
    try:
        plan = service.plan()
        if plan.up_to_date:
            print(f"✔ The index is up to date with {plan.model}; nothing to do.")
            return 0
        batches = math.ceil(plan.chunks_to_embed / cfg.batch_size)
        minutes = math.ceil(max(batches - 1, 0) * cfg.min_seconds_between_batches / 60)
        print(f"Model: {plan.index_model or '(none)'} → {plan.model}")
        print(
            f"Chunks to embed: {plan.chunks_to_embed} in {batches} batches"
            f" (about {minutes} min at the configured pace)"
            + (
                f"; {plan.staged_reusable} vectors reused from an earlier run"
                if plan.staged_reusable
                else ""
            )
        )
        report = service.run(
            on_progress=lambda done, total: print(f"  embedded {done}/{total}", flush=True)
        )
    except KeyboardInterrupt:
        print("\n! Interrupted. The live index is unchanged; finished batches are kept.")
        print("  Run `rag reindex` again to resume.")
        return 130
    except AppError as exc:
        reason = f" ({exc.reason})" if isinstance(exc, ProviderError) else ""
        print(f"✘ {exc.code}: {exc.message_ar}{reason}", file=sys.stderr)
        print("  The live index is unchanged; run `rag reindex` again to resume.", file=sys.stderr)
        return 1
    finally:
        adapter.close()
    if not report.completed:
        print(
            "✘ New documents kept arriving while re-indexing. Stop the app, then run again.",
            file=sys.stderr,
        )
        return 1
    print(
        f"✔ Index now uses {report.model} (dim {report.dim}): {report.vectors} vectors,"
        f" {report.versions} versions, {report.embedded} newly embedded."
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
    sub.add_parser(
        "reindex",
        help="embed every ready version with the configured embedding model (stop the app first)",
    )
    args = parser.parse_args(argv)

    try:
        settings = _load(args.settings)
    except AppError as exc:
        print(f"✘ {exc.code}: {exc.message_ar}", file=sys.stderr)
        return 2
    if args.command == "check":
        return _cmd_check(settings)
    if args.command == "reindex":
        return _cmd_reindex(settings)
    return _cmd_serve(settings)
