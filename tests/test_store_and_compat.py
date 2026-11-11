from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import CorruptedStoreError
from esaa.store import parse_event_store


def _write_lines(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )


def test_legacy_event_is_normalized(tmp_path: Path) -> None:
    _write_lines(
        tmp_path / ".roadmap/activity.jsonl",
        [
            {
                "schema_version": "0.3.0",
                "event_seq": 1,
                "ts": "2026-02-23T16:44:23Z",
                "actor": "orchestrator",
                "action": "run.init",
                "data": {"run_id": "RUN-1", "master_correlation_id": "CID-1"},
            }
        ],
    )

    events = parse_event_store(tmp_path)
    assert len(events) == 1
    assert events[0]["action"] == "run.start"
    assert "payload" in events[0]
    assert events[0]["payload"]["run_id"] == "RUN-1"
    assert events[0]["event_id"] == "LEGACY-EV-00000001"


def test_missing_payload_is_rejected(tmp_path: Path) -> None:
    _write_lines(
        tmp_path / ".roadmap/activity.jsonl",
        [
            {
                "schema_version": "0.4.0",
                "event_id": "EV-00000001",
                "event_seq": 1,
                "ts": "2026-02-23T16:44:23Z",
                "actor": "orchestrator",
                "action": "run.start",
            }
        ],
    )
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(tmp_path)
    assert exc.value.code == "EVENT_MISSING_FIELDS"


def test_unknown_action_is_rejected(tmp_path: Path) -> None:
    _write_lines(
        tmp_path / ".roadmap/activity.jsonl",
        [
            {
                "schema_version": "0.4.0",
                "event_id": "EV-00000001",
                "event_seq": 1,
                "ts": "2026-02-23T16:44:23Z",
                "actor": "orchestrator",
                "action": "does.not.exist",
                "payload": {},
            }
        ],
    )
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(tmp_path)
    assert exc.value.code == "UNKNOWN_ACTION"
