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
