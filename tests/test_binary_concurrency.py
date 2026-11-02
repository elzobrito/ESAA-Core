import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from esaa.binary_artifacts import restore_blob, store_blob
from esaa.binary_payload import stage_binary

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX staging")


def test_concurrent_restore_writes_identical_bytes(tmp_path):
    data = bytes(range(256)) * 8000
    src = tmp_path / "src"
    src.mkdir()
    (src / "blob").write_bytes(data)
    blobs = tmp_path / "blobs"
    sha = hashlib.sha256(data).hexdigest()
    store_blob(src, "blob", blobs, size=len(data), sha256=sha, limit=len(data))
    dests = [tmp_path / f"out-{i}" / "file" for i in range(8)]
    for dest in dests:
        dest.parent.mkdir()

    def restore(dest: Path) -> None:
        restore_blob(blobs, sha, dest, size=len(data), limit=len(data))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, dests))
    for dest in dests:
        assert dest.read_bytes() == data


def test_restore_rejects_symlink_destination_and_parent(tmp_path):
    data = b"payload-bytes"
    src = tmp_path / "src"
    src.mkdir()
    (src / "blob").write_bytes(data)
    blobs = tmp_path / "blobs"
    sha = hashlib.sha256(data).hexdigest()
    store_blob(src, "blob", blobs, size=len(data), sha256=sha, limit=len(data))
    outside = tmp_path / "outside"
    outside.write_bytes(b"old")
    dest = tmp_path / "dest"
    dest.symlink_to(outside)
    with pytest.raises(ValueError, match="regular file"):
        restore_blob(blobs, sha, dest, size=len(data), limit=len(data))
    assert dest.is_symlink()
    assert outside.read_bytes() == b"old"
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(OSError):
        restore_blob(blobs, sha, linked_parent / "file", size=len(data), limit=len(data))
    assert outside.read_bytes() == b"old"


def test_concurrent_stage_from_shared_source(tmp_path):
    data = b"X" * (512 * 1024)
    (tmp_path / "source").write_bytes(data)
    errors: list[BaseException] = []
    results: list[bytes] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            staged = stage_binary(
                tmp_path,
                "source",
                tmp_path,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                limit=len(data),
            )
            payload = staged.read_bytes()
            staged.unlink()
            with lock:
                results.append(payload)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert results == [data] * 6
