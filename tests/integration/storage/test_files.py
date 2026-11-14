from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from rag_app.core.errors import AppError, ErrorCode
from rag_app.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_receive_hashes_streams_and_accept_gives_generated_name(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")
    data = b"%PDF-1.7 " + b"x" * 3_000_000  # larger than one read chunk

    pending = store.receive(io.BytesIO(data), max_bytes=10_000_000)
    name = store.accept(pending, ".pdf")

    assert pending.sha256 == hashlib.sha256(data).hexdigest()
    assert pending.size_bytes == len(data)
    assert pending.head.startswith(b"%PDF-")
    assert name.endswith(".pdf") and len(name) == 36 + 4
    assert store.path_of(name).read_bytes() == data
    assert [p.name for p in store.root.iterdir()] == [name]


def test_oversized_upload_is_rejected_and_leaves_nothing(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")

    with pytest.raises(AppError) as info:
        store.receive(io.BytesIO(b"a" * 2_000_001), max_bytes=2_000_000)

    assert info.value.code is ErrorCode.FILE_TOO_LARGE
    assert list(store.root.iterdir()) == []


def test_empty_upload_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "uploads")

    with pytest.raises(AppError) as info:
        store.receive(io.BytesIO(b""), max_bytes=10)

    assert info.value.code is ErrorCode.EMPTY_FILE
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("name", ["../x.pdf", "a/b.pdf", "..", ""])
def test_path_of_refuses_anything_but_a_plain_name(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="invalid stored file name"):
        FileStore(tmp_path).path_of(name)


def test_sweep_removes_only_unreferenced_files(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    for name in ("keep.pdf", "orphan.md", "stale.part"):
        (tmp_path / name).write_bytes(b"x")

    removed = store.sweep({"keep.pdf"})

    assert sorted(removed) == ["orphan.md", "stale.part"]
    assert [p.name for p in tmp_path.iterdir()] == ["keep.pdf"]


def test_sweep_on_missing_folder_does_nothing(tmp_path: Path) -> None:
    assert FileStore(tmp_path / "absent").sweep(set()) == []
