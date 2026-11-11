import hashlib
import os
import threading

import pytest

from esaa.binary_artifacts import assert_safe_destination, restore_blob, store_blob
from esaa.binary_payload import stage_binary
from esaa.bootstrap import bootstrap_workspace
from esaa.errors import ESAAError
from esaa.file_effects import commit_staged, stage_file_updates
from esaa.service import ESAAService

pytestmark = pytest.mark.skipif(os.name != "posix", reason="secure POSIX dirfd required")


def test_destination_symlink_and_parent_symlink_rejected(tmp_path):
    target = tmp_path / "out.bin"
    evil = tmp_path / "evil.bin"
    evil.write_bytes(b"keep")
    target.symlink_to(evil)
    with pytest.raises(ValueError):
        assert_safe_destination(target)
    assert evil.read_bytes() == b"keep"
    parent = tmp_path / "linked"
    outside = tmp_path / "outside"
    outside.mkdir()
    parent.symlink_to(outside, target_is_directory=True)
    dest = parent / "file.bin"
    with pytest.raises(OSError):
        assert_safe_destination(dest)


def test_restore_does_not_follow_destination_symlink(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    source = tmp_path / "src.bin"
    data = b"payload-bytes"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    store_blob(tmp_path, "src.bin", blob_dir, size=len(data), sha256=digest, limit=len(data))
    evil = tmp_path / "secret"
    evil.write_bytes(b"original")
    dest = tmp_path / "dest.bin"
    dest.symlink_to(evil)
    with pytest.raises(ValueError):
        restore_blob(blob_dir, digest, dest, size=len(data), limit=len(data))
    assert evil.read_bytes() == b"original"


def test_source_replacement_after_open_keeps_original_bytes(tmp_path, monkeypatch):
    data = os.urandom(2 * 1024 * 1024)
    source = tmp_path / "source"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    original_read = os.read
    replaced = {"done": False}

    def swapping_read(fd, n):
        chunk = original_read(fd, n)
        if chunk and not replaced["done"]:
            source.unlink()
            source.write_bytes(b"x" * len(data))
            replaced["done"] = True
        return chunk

    monkeypatch.setattr(os, "read", swapping_read)
    staged = stage_binary(tmp_path, "source", tmp_path, size=len(data), sha256=digest, limit=len(data))
    assert staged.read_bytes() == data
    assert replaced["done"] is True


def test_in_place_source_rewrite_is_rejected(tmp_path, monkeypatch):
    data = os.urandom(2 * 1024 * 1024)
    source = tmp_path / "source"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    original_read = os.read
    rewritten = {"done": False}

    def mutating_read(fd, n):
        chunk = original_read(fd, n)
        if chunk and not rewritten["done"]:
            source.write_bytes(b"x" * len(data))
            rewritten["done"] = True
        return chunk

    monkeypatch.setattr(os, "read", mutating_read)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        stage_binary(tmp_path, "source", tmp_path, size=len(data), sha256=digest, limit=len(data))
    assert not list(tmp_path.glob("binary-*"))


def test_commit_rejects_destination_swap_to_symlink(tmp_path):
    bootstrap_workspace(tmp_path)
    source_root = tmp_path / ".roadmap/binary-input" / hashlib.sha256(b"A").hexdigest()
    source_root.mkdir(parents=True)
    payload = b"abcdefg"
    digest = hashlib.sha256(payload).hexdigest()
    (source_root / digest).write_bytes(payload)
    (tmp_path / "src").mkdir()
    updates = [{"path": "src/out.bin", "binary": {"source": digest, "size": len(payload), "sha256": digest}}]
    staged = stage_file_updates(tmp_path, updates, task_id="A")
    evil = tmp_path / "outside.bin"
    evil.write_bytes(b"untouched")
    dest = tmp_path / "src/out.bin"
    dest.symlink_to(evil)
    with pytest.raises(ValueError):
        commit_staged(tmp_path, staged)
    assert evil.read_bytes() == b"untouched"


def test_store_lock_serializes_concurrent_complete(tmp_path):
    bootstrap_workspace(tmp_path)
    svc = ESAAService(tmp_path)
    svc.init()
    svc.create_task("T", task_kind="impl", title="T")
    svc.claim_task("T", actor="agent-impl")
    errors = []

    def complete():
        try:
            ESAAService(tmp_path).complete_task("T", actor="agent-impl", checks=["one"])
        except ESAAError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=complete) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    status = ESAAService(tmp_path).task_state("T")["task"]["status"]
    assert status == "review"
    assert errors == [] or set(errors) <= {
        "STALE_STATE_SEQ",
        "STALE_STATE_HASH",
        "WRITE_CONFLICT",
        "INVALID_TRANSITION",
        "WORKFLOW_GATE_VIOLATION",
    }
