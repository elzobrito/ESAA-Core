from __future__ import annotations

from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService, make_event
from esaa.store import (
    _verify_appended_lines,
    append_events,
    next_event_seq,
    parse_event_store,
    reset_concurrency_metrics,
    snapshot_concurrency_metrics,
)


def _verify_start(seq: int, marker: str) -> dict:
    return make_event(seq, "orchestrator", "verify.start", {"strict": True, "marker": marker})


def test_service_retries_stale_state_and_preserves_monotonic_seq(contract_bundle: Path) -> None:
    reset_concurrency_metrics()
    svc = ESAAService(contract_bundle)
    svc.init(force=True)
    base_events = parse_event_store(contract_bundle)
    stale_seq = next_event_seq(base_events)

    append_events(contract_bundle, [_verify_start(stale_seq, "concurrent")])
    stale_candidate = [_verify_start(stale_seq, "retry")]

    result = svc._append_events_transactionally(base_events, stale_candidate)
    events = parse_event_store(contract_bundle)
    seqs = [event["event_seq"] for event in events]
    metrics = svc.metrics()["concurrency"]

    assert result["events_appended"] == 1
    assert seqs == list(range(1, len(events) + 1))
    assert events[-1]["payload"]["marker"] == "retry"
    assert events[-1]["event_seq"] == stale_seq + 1
    assert metrics["stale_conflicts"] >= 1
    assert metrics["submit_retries"] >= 1


def test_read_after_write_mismatch_raises_append_verify_failed(tmp_path: Path) -> None:
    reset_concurrency_metrics()
    path = tmp_path / ".roadmap" / "activity.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"actual":true}\n', encoding="utf-8")

    with pytest.raises(ESAAError) as excinfo:
        _verify_appended_lines(path, ['{"expected":true}'])

    assert excinfo.value.code == "APPEND_VERIFY_FAILED"
    assert snapshot_concurrency_metrics()["append_verify_failed"] == 1
