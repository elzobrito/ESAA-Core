"""Content-addressed binary blob primitives; integration must authorize paths."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .binary_payload import stage_binary

_HASH = re.compile(r'^[0-9a-f]{64}$')


def _validate(size: int, digest: str) -> None:
    if type(size) is not int or size < 0 or not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ValueError('invalid blob metadata')


def store_blob(source_root: Path, relative: str, blob_dir: Path, *, size: int, sha256: str, limit: int) -> Path:
    """Store verified bytes under their SHA-256; blob_dir must be private and trusted."""
    _validate(size, sha256)
    blob_dir = Path(blob_dir)
    blob_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_binary(source_root, relative, blob_dir, size=size, sha256=sha256, limit=limit)
    final = blob_dir / sha256
    try:
        try:
            os.link(staged, final, follow_symlinks=False)
        except FileExistsError:
            # Never trust an existing path solely because its name is the digest.
            verified = stage_binary(blob_dir, sha256, blob_dir, size=size, sha256=sha256, limit=limit)
            verified.unlink()
        return final
    finally:
        staged.unlink(missing_ok=True)


def assert_safe_destination(target: Path) -> None:
    """Reject symlink parents and symlink/non-file destinations before replace."""
    target = Path(target)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(parent, flags)
        try:
            try:
                info = os.stat(target.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise ValueError("destination must be absent or a regular file")
        finally:
            os.close(fd)
        return
    if parent.is_symlink():
        raise ValueError("destination directory must not be a symlink")
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise ValueError("destination must be absent or a regular file")


def restore_blob(blob_dir: Path, sha256: str, target: Path, *, size: int, limit: int) -> None:
    """Verify into target directory then atomically replace; caller validates destination."""
    _validate(size, sha256)
    target = Path(target)
    assert_safe_destination(target)
    staged = stage_binary(Path(blob_dir), sha256, target.parent, size=size, sha256=sha256, limit=limit)
    try:
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)
