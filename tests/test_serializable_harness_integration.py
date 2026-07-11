from __future__ import annotations

from pathlib import Path

import pytest

import esaa.service_core as service_core_module
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _forbid_append_events(*_args, **_kwargs) -> None:
    raise ESAAError("APPEND_EVENTS_BYPASS", "append_events must not be used by governed harness paths")


def test_submit_claim_uses_serializable_transaction(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    monkeypatch.setattr(service_core_module, "append_events", _forbid_append_events)

    result = svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    assert result["status"] == "accepted"
    assert result["verify_status"] == "ok"
    events = parse_event_store(contract_bundle)
    assert any(event["action"] == "claim" and event["payload"]["task_id"] == "T-1000" for event in events)


def test_run_claim_uses_serializable_transaction(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    monkeypatch.setattr(service_core_module, "append_events", _forbid_append_events)

    result = svc.run(steps=1)

    assert result["steps_executed"] == 1
    assert result["verify_status"] == "ok"
    events = parse_event_store(contract_bundle)
    assert any(event["action"] == "claim" and event["payload"]["task_id"] == "T-1000" for event in events)


def test_orchestrator_command_uses_serializable_transaction(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    monkeypatch.setattr(service_core_module, "append_events", _forbid_append_events)

    result = svc.create_task(
        "TX-1",
        "spec",
        "Serializable command path",
        outputs=["docs/spec/TX-1.md"],
    )

    assert result["status"] == "accepted"
    assert result["verify_status"] == "ok"
    events = parse_event_store(contract_bundle)
    assert any(event["action"] == "task.create" and event["payload"]["task_id"] == "TX-1" for event in events)
