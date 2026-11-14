"""FileStore: original uploaded files under generated names in the data folder (NFR-SEC-02).

User-supplied names never become paths: every file is stored as ``<uuid><ext>``. Uploads are
streamed to a temporary ``.part`` file with a running size check and SHA-256 hash, so a file
over the limit is rejected without ever being held in memory or kept on disk.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from rag_app.core.errors import AppError, ErrorCode
from rag_app.core.ids import new_id

logger = logging.getLogger(__name__)

_CHUNK_BYTES = 1024 * 1024
_HEAD_BYTES = 1024
_PART_SUFFIX = ".part"


@dataclass(frozen=True, slots=True)
class PendingFile:
    """An upload written to a temporary file, not yet accepted."""

    path: Path
    size_bytes: int
    sha256: str
    head: bytes


class FileStore:
    """Owns the uploads folder; the only code that creates or deletes files in it."""

    def __init__(self, root: Path) -> None:
        """Use ``root`` as the uploads folder; it is created on first write."""
        self.root = root

    def receive(self, stream: BinaryIO, *, max_bytes: int) -> PendingFile:
        """Stream ``stream`` to a temporary file, enforcing ``max_bytes``.

        Raises:
            AppError: ``FILE_TOO_LARGE`` (the partial file is removed) or ``EMPTY_FILE``.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{new_id()}{_PART_SUFFIX}"
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            with path.open("xb") as out:
                while chunk := stream.read(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AppError(
                            ErrorCode.FILE_TOO_LARGE, limit_mb=max_bytes // (1024 * 1024)
                        )
                    if len(head) < _HEAD_BYTES:
                        head += chunk[: _HEAD_BYTES - len(head)]
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise AppError(ErrorCode.EMPTY_FILE)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return PendingFile(path, size, digest.hexdigest(), head)

    def accept(self, pending: PendingFile, extension: str) -> str:
        """Give a received file its final generated name and return that name."""
        final = pending.path.with_name(pending.path.name.removesuffix(_PART_SUFFIX) + extension)
        pending.path.replace(final)  # atomic rename on the same volume
        return final.name

    def discard(self, pending: PendingFile) -> None:
        """Remove a received file that was not accepted."""
        pending.path.unlink(missing_ok=True)

    def path_of(self, stored_name: str) -> Path:
        """Absolute path of a stored file; rejects anything that is not a plain file name."""
        if Path(stored_name).name != stored_name or stored_name in {"", ".", ".."}:
            msg = f"invalid stored file name: {stored_name!r}"
            raise ValueError(msg)
        return self.root / stored_name

    def delete(self, stored_names: Iterable[str]) -> list[str]:
        """Delete stored files; return the names that could not be deleted.

        Called only after the database rows are gone (DESIGN-001 §7.2). A failure, e.g. a
        file locked on Windows, leaves an orphan that :meth:`sweep` removes later.
        """
        failed = []
        for name in stored_names:
            try:
                self.path_of(name).unlink(missing_ok=True)
            except OSError:
                logger.warning("file_delete_failed", extra={"stored_name": name}, exc_info=True)
                failed.append(name)
        return failed

    def sweep(self, referenced: set[str]) -> list[str]:
        """Delete files that no version references (orphans and stale ``.part`` files)."""
        if not self.root.is_dir():
            return []
        orphans = [p.name for p in self.root.iterdir() if p.is_file() and p.name not in referenced]
        failed = set(self.delete(orphans))
        removed = [name for name in orphans if name not in failed]
        if removed:
            logger.info("orphan_files_removed", extra={"count": len(removed)})
        return removed
