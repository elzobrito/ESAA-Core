"""Bounded, hash-verified staging of files beneath a trusted input directory.

This module is a building block; it does not authorize or commit file effects.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

_CHUNK = 1024 * 1024
_HASH = re.compile(r"^[a-f0-9]{64}$")


def _open_confined(root: Path, relative: str) -> int:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise NotImplementedError("secure dirfd traversal is unavailable")
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ValueError("invalid source path")
    parts = relative.split("/")
    if relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError("source must be a normalized relative path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    return result


def stage_binary(root: Path, relative: str, staging: Path, *, size: int, sha256: str, limit: int) -> Path:
    """Stage bytes from a confined regular file; caller owns returned staged file.

    staging must be a private directory owned by the orchestrator. Size and hash
    are checked against bytes actually copied, and failed stages are deleted.
    """
    if (
        type(size) is not int
        or type(limit) is not int
        or size < 0
        or limit < 0
        or size > limit
        or not isinstance(sha256, str)
        or not _HASH.fullmatch(sha256)
    ):
        raise ValueError("invalid size, limit or SHA-256")
    source_fd = _open_confined(Path(root), relative)
    staged_path = None
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != size:
            raise ValueError("source must be a single-link regular file of declared size")
        fd, name = tempfile.mkstemp(prefix="binary-", suffix=".tmp", dir=staging)
        staged_path = Path(name)
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(fd, "wb") as target:
            while True:
                chunk = os.read(source_fd, _CHUNK)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > size or copied > limit:
                    raise ValueError("source exceeded declared size or limit")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if copied != size or digest.hexdigest() != sha256:
            raise ValueError("source size or SHA-256 mismatch")
        return staged_path
    except BaseException:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)
