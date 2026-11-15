"""IngestionWorker: processes queued document versions in one background thread.

One thread is enough for a single user (D-009) and keeps SQLite writes serialised. The worker
claims a job, runs the pure pipeline stages in memory, and writes the result in one
transaction (DESIGN-001 §7.1). Between stages it records progress; if the version has been
deleted meanwhile, it stops and discards its work (DD-02).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import cache

from rag_app.config.settings import Settings
from rag_app.core.errors import CATALOG, AppError, ErrorCode
from rag_app.domain.models import ClaimedJob, ProcessingStage
from rag_app.ingestion.pipeline import process_file
from rag_app.ingestion.poppler import PopplerTools, locate_poppler
from rag_app.providers.openai_compatible import RetryPolicy, build_embedder
from rag_app.providers.ports import EmbeddingProvider
from rag_app.storage.db import Database
from rag_app.storage.files import FileStore
from rag_app.storage.repositories.documents import DocumentRepository, RecoveryReport

logger = logging.getLogger(__name__)


class _CancelledError(Exception):
    """The version was deleted while it was being processed."""


class IngestionWorker:
    """Runs ingestion jobs; start/stop with the application, or drive it directly in tests."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        files: FileStore,
        poppler: Callable[[], PopplerTools] | None = None,
        embedder: Callable[[], EmbeddingProvider] | None = None,
    ) -> None:
        """Wire the worker. Poppler and the embedding provider are created on first use.

        A missing key or Poppler therefore fails the affected version with a clear message
        instead of stopping the app.
        """
        self._settings = settings
        self._repo = DocumentRepository(db)
        self._files = files
        self._poppler = poppler or cache(lambda: locate_poppler(settings.poppler_dir))
        retry = RetryPolicy(
            settings.ingestion.embed_max_attempts, settings.ingestion.embed_first_backoff_seconds
        )
        self._embedder: Callable[[], EmbeddingProvider] = embedder or cache(
            lambda: build_embedder(settings.providers.embedding, retry)
        )
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def recover(self) -> RecoveryReport:
        """Re-queue jobs interrupted by a crash or restart (FR-ING-14); call before start."""
        report = self._repo.recover_interrupted(
            self._settings.ingestion.max_attempts, CATALOG[ErrorCode.INTERRUPTED].message_ar
        )
        if report.requeued or report.failed:
            logger.warning(
                "ingestion_recovered",
                extra={"requeued": report.requeued, "failed": report.failed},
            )
        return report

    def start(self) -> None:
        """Start the background thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ingestion-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Ask the thread to finish its current job and wait for it.

        A job still running after ``timeout`` is left ``running`` and is recovered at the
        next start-up, so stopping never loses an upload.
        """
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def wake(self) -> None:
        """Signal that a job was queued, so it starts without waiting for the next poll."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                # A bug or a database problem must not kill the thread silently.
                logger.exception("ingestion_loop_error")
                worked = False
            if not worked:
                self._wake.wait(self._settings.ingestion.poll_seconds)
                self._wake.clear()

    # ------------------------------------------------------------------ work
    def run_until_idle(self) -> int:
        """Process every queued job in the calling thread; return how many ran (tests, CLI)."""
        count = 0
        while self.run_once():
            count += 1
        return count

    def run_once(self) -> bool:
        """Claim and process one job; return ``False`` when the queue is empty."""
        job = self._repo.claim_next_job()
        if job is None:
            return False
        log = {"job_id": job.job_id, "version_id": job.version_id, "attempt": job.attempts}
        logger.info("ingestion_started", extra=log)
        try:
            result = process_file(
                self._files.path_of(job.stored_name),
                job.format,
                self._settings.rag,
                poppler=self._poppler,
                embedder=self._embedder,
                timeout=self._settings.ingestion.extraction_timeout_seconds,
                on_stage=lambda stage: self._progress(job, stage),
            )
            self._progress(job, ProcessingStage.INDEXING)
        except _CancelledError:
            logger.info("ingestion_cancelled", extra=log)
            return True
        except AppError as exc:
            self._fail(job, exc.code, exc.message_ar, log)
            return True
        except Exception:
            logger.exception("ingestion_crashed", extra=log)
            self._fail(job, ErrorCode.INTERNAL_ERROR, None, log)
            return True

        if self._repo.complete_ingestion(
            job, result.chunks, result.page_count, result.vectors, result.embedding
        ):
            logger.info("ingestion_done", extra={**log, "chunks": len(result.chunks)})
        else:
            logger.info("ingestion_cancelled", extra=log)
        return True

    def _progress(self, job: ClaimedJob, stage: ProcessingStage) -> None:
        if not self._repo.set_stage(job.version_id, stage):
            raise _CancelledError

    def _fail(
        self, job: ClaimedJob, code: ErrorCode, message: str | None, log: dict[str, object]
    ) -> None:
        self._repo.fail_ingestion(job, code.value, message or CATALOG[code].message_ar)
        logger.warning("ingestion_failed", extra={**log, "error_code": code.value})
