from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import ESAA_VERSION
from .store import _acquire_store_lock, _release_store_lock, snapshot_concurrency_metrics
from .utils import utc_now_iso

ENV_ESAA_LOG = "ESAA_LOG"


def oplog_path_from_env() -> Path | None:
    raw = os.environ.get(ENV_ESAA_LOG, "").strip()
    return Path(raw) if raw else None


def emit_oplog_entry(
    *,
    command: str | None,
    runner: str | None,
    root: Path | None,
    duration_ms: int,
    exit_code: int,
    error_code: str | None,
    dry_run: bool,
) -> None:
    """Append one structured JSON operational log line if ESAA_LOG is set.

    Any I/O or OS error is swallowed silently so logging never alters stdout,
    stderr, or the command's exit code.
    """
    log_path = oplog_path_from_env()
    if log_path is None:
        return
    try:
        metrics = snapshot_concurrency_metrics()
        entry: dict[str, Any] = {
            "ts": utc_now_iso(),
            "esaa_version": ESAA_VERSION,
            "pid": os.getpid(),
            "command": command,
            "runner": runner,
            "root": str(root) if root is not None else None,
            "duration_ms": max(0, int(duration_ms)),
            "lock_wait_ms": metrics["lock_wait_ms"],
            "lock_retries": metrics["lock_retries"],
            "lock_takeovers": metrics["lock_takeovers"],
            "events_appended": metrics["events_appended"],
            "exit_code": int(exit_code),
            "error_code": error_code,
            "dry_run": bool(dry_run),
        }
        payload = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize appends: Windows O_APPEND is not atomic across processes.
        lock_path = _acquire_store_lock(log_path, timeout=5.0, retry_interval=0.01, lock_max_age=15.0)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            fd = os.open(str(log_path), flags, 0o666)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        finally:
            _release_store_lock(lock_path)
    except Exception:
        return
