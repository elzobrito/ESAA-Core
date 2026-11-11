"""Same-directory atomic replacement with flushed file and directory metadata."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4


def sync_directory(directory: Path) -> None:
    # Windows does not expose a directory handle usable by os.fsync. The file
    # itself is still flushed there, and os.replace remains an atomic rename.
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one file, retaining its existing permissions and exact bytes.

    Failures before replacement leave the old destination intact and remove
    the temporary file. Multiple read models are individually atomic, not a
    multi-file transaction; replay remains the recovery mechanism.
    """
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        sync_directory(directory.parent)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() and not path.is_symlink() else None
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if mode is not None and hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
