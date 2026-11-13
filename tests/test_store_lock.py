from __future__ import annotations

from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import make_event
from esaa.store import append_events, parse_event_store


def test_append_events_uses_filesystem_lock_timeout(tmp_path: Path) -> None:
    lock_path = tmp_path / ".roadmap" / "activity.jsonl.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    with pytest.raises(ESAAError) as exc:
        append_events(
            tmp_path,
            [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})],
            lock_timeout=0.05,
            retry_interval=0.01,
        )

    assert exc.value.code == "STORE_LOCK_TIMEOUT"


def test_append_events_releases_lock_after_success(tmp_path: Path) -> None:
    append_events(tmp_path, [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})])

    assert not (tmp_path / ".roadmap" / "activity.jsonl.lock").exists()
    assert parse_event_store(tmp_path)[0]["action"] == "run.start"


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_sharing_on_release_does_not_repeat_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int
) -> None:
    import esaa.store as store

    original = Path.unlink
    attempts = []
    sleeps = []

    def unlink(path, *args, **kwargs):
        if path.name == "activity.jsonl.lock":
            attempts.append(path)
            if len(attempts) < 3:
                error = PermissionError("temporary Windows sharing violation")
                error.winerror = winerror
                raise error
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(store.time, "sleep", sleeps.append)
    append_events(tmp_path, [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})])
    assert len(attempts) == 3 and len(sleeps) == 2
    assert [e["event_seq"] for e in parse_event_store(tmp_path)] == [1]
    assert not (tmp_path / ".roadmap/activity.jsonl.lock").exists()


@pytest.mark.parametrize("winerror", [None, 5, 32])
def test_release_does_not_hide_permissions_or_unbounded_sharing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int | None
) -> None:
    from esaa.store import _release_store_lock

    lock = tmp_path / "owned.lock"
    lock.write_text("owned", encoding="utf-8")
    error = PermissionError("release denied")
    if winerror is not None:
        error.winerror = winerror
    calls = []

    def unlink(path, *args, **kwargs):
        calls.append(path)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", unlink)
        with pytest.raises(PermissionError) as exc:
            _release_store_lock(lock, timeout=0)
        assert exc.value is error
    assert len(calls) == 1 and lock.exists()


def _windows_permission_denied(winerror: int | None) -> PermissionError:
    error = PermissionError("[Errno 13] Permission denied")
    error.errno = 13
    if winerror is not None:
        error.winerror = winerror
    return error


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_transient_windows_access_denied_on_acquire_does_not_repeat_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int
) -> None:
    import esaa.store as store

    original_open = store.os.open
    attempts = []
    sleeps = []

    def open_lock(path, flags, *args, **kwargs):
        if Path(path).name == "activity.jsonl.lock" and flags & store.os.O_EXCL:
            attempts.append(path)
            if len(attempts) < 3:
                raise _windows_permission_denied(winerror)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store.os, "open", open_lock)
    monkeypatch.setattr(store.time, "sleep", sleeps.append)
    append_events(tmp_path, [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})])
    assert len(attempts) == 3 and len(sleeps) == 2
    assert [e["event_seq"] for e in parse_event_store(tmp_path)] == [1]
    assert not (tmp_path / ".roadmap/activity.jsonl.lock").exists()


def test_persistent_windows_access_denied_on_acquire_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import esaa.store as store

    original_open = store.os.open
    attempts = []

    def open_lock(path, flags, *args, **kwargs):
        if Path(path).name == "activity.jsonl.lock":
            attempts.append(path)
            raise _windows_permission_denied(5)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store.os, "open", open_lock)
    with pytest.raises(ESAAError) as exc:
        append_events(
            tmp_path,
            [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})],
            lock_timeout=0,
            retry_interval=0.01,
        )
    assert exc.value.code == "STORE_LOCK_TIMEOUT"
    assert attempts
    assert parse_event_store(tmp_path) == []


def test_acquire_permission_error_without_winerror_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import esaa.store as store

    original_open = store.os.open
    attempts = []
    error = _windows_permission_denied(None)

    def open_lock(path, flags, *args, **kwargs):
        if Path(path).name == "activity.jsonl.lock":
            attempts.append(path)
            raise error
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store.os, "open", open_lock)
    with pytest.raises(PermissionError) as exc:
        append_events(
            tmp_path,
            [make_event(1, "orchestrator", "run.start", {"run_id": "RUN-L"})],
            lock_timeout=1.0,
            retry_interval=0.01,
        )
    assert exc.value is error
    assert len(attempts) == 1
