"""FIX-1806-QA — Serializable append transaction tests.

Cobre:
- caminho feliz (append + project)
- expected_first_seq mismatch -> STALE_STATE_SEQ
- expected_projection_hash mismatch -> STALE_STATE_HASH
- lock timeout -> STORE_LOCK_TIMEOUT
- nenhum duplicate event_seq, nenhum gap
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import (
    _acquire_store_lock,
    _release_store_lock,
    append_transactional,
    next_event_seq,
    parse_event_store,
)


def _event(seq, action, payload):
    return {
        "schema_version": "0.4.1",
        "event_id": f"EV-{seq:08d}",
        "event_seq": seq,
        "ts": "2026-05-23T15:00:00Z",
        "actor": "orchestrator",
        "action": action,
        "payload": payload,
    }


def test_append_transactional_happy_path(contract_bundle: Path) -> None:
    """Caminho normal: build_events_fn cria evento, append + project sob lock."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    start_seq = next_event_seq(events)

    def build_fn(current_events):
        seq = next_event_seq(current_events)
        return [_event(seq, "verify.start", {"strict": True, "trigger": "ad-hoc"})]

    result = append_transactional(contract_bundle, build_fn)
    assert result["events_appended"] == 1
    assert result["last_event_seq"] == start_seq

    final = parse_event_store(contract_bundle)
    assert final[-1]["action"] == "verify.start"


def test_append_transactional_stale_state_seq(contract_bundle: Path) -> None:
    """expected_first_seq desatualizado -> STALE_STATE_SEQ."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    actual_next = next_event_seq(events)

    with pytest.raises(ESAAError) as exc:
        append_transactional(
            contract_bundle,
            lambda evs: [],
            expected_first_seq=actual_next + 99,
        )
    assert exc.value.code == "STALE_STATE_SEQ"


def test_append_transactional_stale_state_hash(contract_bundle: Path) -> None:
    """expected_projection_hash divergente -> STALE_STATE_HASH."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    with pytest.raises(ESAAError) as exc:
        append_transactional(
            contract_bundle,
            lambda evs: [],
            expected_projection_hash="00" * 32,
        )
    assert exc.value.code == "STALE_STATE_HASH"


def test_append_transactional_lock_timeout(contract_bundle: Path) -> None:
    """Lock segurado externamente -> STORE_LOCK_TIMEOUT."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    store_path = contract_bundle / ".roadmap" / "activity.jsonl"
    lock = _acquire_store_lock(store_path, timeout=1.0)
    try:
        with pytest.raises(ESAAError) as exc:
            append_transactional(contract_bundle, lambda evs: [], timeout=0.2)
        assert exc.value.code == "STORE_LOCK_TIMEOUT"
    finally:
        _release_store_lock(lock)


def test_append_transactional_no_duplicate_seq(contract_bundle: Path) -> None:
    """Multiplos appends transacionais: seq monotonico, sem gaps."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    for _ in range(3):
        def build_fn(current_events):
            seq = next_event_seq(current_events)
            return [_event(seq, "verify.start", {"strict": True})]
        append_transactional(contract_bundle, build_fn)

    events = parse_event_store(contract_bundle)
    seqs = [e["event_seq"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1))  # contiguo
    assert len(set(seqs)) == len(seqs)  # sem duplicatas
