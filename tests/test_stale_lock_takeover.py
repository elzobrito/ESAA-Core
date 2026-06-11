from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import make_event
from esaa.store import _lock_path, append_events, ensure_event_store, parse_event_store, reset_concurrency_metrics


def _lock_metadata(pid: int, hostname: str, acquired_at: datetime | None = None) -> str:
    ts = acquired_at or datetime.now(timezone.utc)
    return json.dumps(
        {
            "pid": pid,
            "hostname": hostname,
            "runner_id": "qa-lock",
            "acquired_at": ts.isoformat().replace("+00:00", "Z"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _run_start(seq: int = 1) -> dict:
    return make_event(seq, "orchestrator", "run.start", {"run_id": f"RUN-{seq}"})


def test_dead_local_pid_lock_is_taken_over_quickly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reset_concurrency_metrics()
    store = ensure_event_store(tmp_path)
    lock = _lock_path(store)
    lock.write_text(_lock_metadata(999999, socket.gethostname()), encoding="utf-8")

    append_events(tmp_path, [_run_start()], lock_timeout=1.0, retry_interval=0.01)

    stderr = capsys.readouterr().err
    assert "LOCK_TAKEOVER" in stderr
    assert "dead_local_pid" in stderr
    assert not lock.exists()
    assert parse_event_store(tmp_path)[0]["action"] == "run.start"


def test_live_local_pid_lock_is_not_taken_even_after_max_age(tmp_path: Path) -> None:
    store = ensure_event_store(tmp_path)
    lock = _lock_path(store)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    lock.write_text(_lock_metadata(os.getpid(), socket.gethostname(), old), encoding="utf-8")

    with pytest.raises(ESAAError) as excinfo:
        append_events(
            tmp_path,
            [_run_start()],
            lock_timeout=0.05,
            retry_interval=0.01,
            lock_max_age=0.0,
        )

    assert excinfo.value.code == "STORE_LOCK_TIMEOUT"
    assert lock.exists()


def test_cross_host_lock_waits_for_ttl_then_takes_over(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = ensure_event_store(tmp_path)
    lock = _lock_path(store)
    lock.write_text(_lock_metadata(999999, "other-host.invalid"), encoding="utf-8")

    with pytest.raises(ESAAError) as excinfo:
        append_events(
            tmp_path,
            [_run_start()],
            lock_timeout=0.05,
            retry_interval=0.01,
            lock_max_age=120.0,
        )
    assert excinfo.value.code == "STORE_LOCK_TIMEOUT"
    assert lock.exists()

    append_events(
        tmp_path,
        [_run_start()],
        lock_timeout=1.0,
        retry_interval=0.01,
        lock_max_age=0.0,
    )

    stderr = capsys.readouterr().err
    assert "LOCK_TAKEOVER" in stderr
    assert "cross_host_ttl_expired" in stderr
    assert parse_event_store(tmp_path)[0]["action"] == "run.start"
