"""FIX-1572 — Attempt lifecycle (R2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from esaa.runtime_policy import (
    attempt_expired,
    count_penalizing_rejections,
    is_blocked_by_max_attempts,
    is_in_cooldown,
    parse_duration,
)


def _ev(seq, action, payload, ts=None):
    return {
        "event_seq": seq,
        "action": action,
        "ts": ts or "2026-05-23T08:00:00Z",
        "actor": "orchestrator",
        "payload": payload,
    }


def test_parse_duration():
    assert parse_duration("PT2M") == timedelta(minutes=2)
    assert parse_duration("PT30M") == timedelta(minutes=30)
    assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)


def test_count_penalizing_rejections_excludes_prior_mismatch():
    events = [
        _ev(1, "output.rejected", {"task_id": "T", "error_code": "SCHEMA_INVALID"}),
        _ev(2, "output.rejected", {"task_id": "T", "error_code": "PRIOR_STATUS_MISMATCH"}),
        _ev(3, "output.rejected", {"task_id": "T", "error_code": "BOUNDARY_VIOLATION"}),
    ]
    assert count_penalizing_rejections(events, "T") == 2


def test_max_attempts_blocks_at_three():
    events = [
        _ev(i, "output.rejected", {"task_id": "T", "error_code": "SCHEMA_INVALID"}) for i in range(1, 4)
    ]
    assert is_blocked_by_max_attempts(events, "T", max_attempts=3)
    assert not is_blocked_by_max_attempts(events, "T", max_attempts=4)


def test_prior_mismatch_does_not_block():
    events = [
        _ev(i, "output.rejected", {"task_id": "T", "error_code": "PRIOR_STATUS_MISMATCH"})
        for i in range(1, 6)
    ]
    assert not is_blocked_by_max_attempts(events, "T", max_attempts=3)


def test_cooldown_active_in_window():
    now = datetime(2026, 5, 23, 8, 1, 0, tzinfo=UTC)
    events = [
        _ev(1, "output.rejected", {"task_id": "T", "error_code": "SCHEMA_INVALID"}, ts="2026-05-23T08:00:00Z")
    ]
    assert is_in_cooldown(events, "T", now, timedelta(minutes=2))
    later = datetime(2026, 5, 23, 8, 3, 0, tzinfo=UTC)
    assert not is_in_cooldown(events, "T", later, timedelta(minutes=2))


def test_attempt_expired_when_claim_old_and_no_complete():
    now = datetime(2026, 5, 23, 9, 0, 0, tzinfo=UTC)
    events = [_ev(1, "claim", {"task_id": "T"}, ts="2026-05-23T08:00:00Z")]
    assert attempt_expired(events, "T", now, timedelta(minutes=30))
    # com complete posterior nao expira
    events.append(_ev(2, "complete", {"task_id": "T"}, ts="2026-05-23T08:15:00Z"))
    assert not attempt_expired(events, "T", now, timedelta(minutes=30))
