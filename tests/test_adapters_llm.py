"""Tests for esaa submit and esaa process (file-based agent interface)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


# ---------------------------------------------------------------------------
# esaa submit
# ---------------------------------------------------------------------------


def test_submit_claim_accepted(contract_bundle: Path) -> None:
    """An agent can claim a todo task via submit."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    agent_output = {
        "activity_event": {
            "action": "claim",
            "task_id": "T-1000",
            "prior_status": "todo",
            "notes": "claiming spec task",
        }
    }
    result = service.submit(agent_output, actor="agent-spec")
    assert result["status"] == "accepted"
    assert result["action"] == "claim"
    assert result["task_id"] == "T-1000"
    assert result["verify_status"] == "ok"


def test_submit_complete_with_files(contract_bundle: Path) -> None:
    """An agent can complete a task and write files via submit."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    service.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    result = service.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": "T-1000",
                "prior_status": "in_progress",
                "verification": {"checks": ["manual-review"]},
            },
            "file_updates": [
                {"path": "docs/spec/T-1000.md", "content": "# Spec\nContent here.\n"}
            ],
        },
        actor="agent-spec",
    )
    assert result["status"] == "accepted"
    assert result["files_written"] == 1
    assert (contract_bundle / "docs/spec/T-1000.md").exists()


def test_submit_boundary_violation_rejected(contract_bundle: Path) -> None:
    """Submit rejects files outside agent boundaries."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    service.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    with pytest.raises(ESAAError) as exc:
        service.submit(
            {
                "activity_event": {
                    "action": "complete",
                    "task_id": "T-1000",
                    "prior_status": "in_progress",
                    "verification": {"checks": ["ok"]},
                },
                "file_updates": [{"path": "src/evil.py", "content": "hack"}],
            },
            actor="agent-spec",
        )
    assert exc.value.code == "BOUNDARY_VIOLATION"


def test_submit_invalid_task_rejected(contract_bundle: Path) -> None:
    """Submit rejects unknown task_id."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    with pytest.raises(ESAAError) as exc:
        service.submit(
            {"activity_event": {"action": "claim", "task_id": "T-9999", "prior_status": "todo"}},
            actor="agent-spec",
        )
    assert exc.value.code == "TASK_NOT_FOUND"


def test_submit_dry_run_no_persist(contract_bundle: Path) -> None:
    """Dry run validates but does not persist."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    events_before = parse_event_store(contract_bundle)
    result = service.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["would_append_events"] >= 1
    events_after = parse_event_store(contract_bundle)
    assert len(events_after) == len(events_before)


def test_submit_full_lifecycle(contract_bundle: Path) -> None:
    """Full claim -> complete -> review cycle via submit."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    service.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    service.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": "T-1000",
                "prior_status": "in_progress",
                "verification": {"checks": ["reviewed"]},
            },
            "file_updates": [
                {"path": "docs/spec/T-1000.md", "content": "# Spec\n"}
            ],
        },
        actor="agent-spec",
    )
    result = service.submit(
        {
            "activity_event": {
                "action": "review",
                "task_id": "T-1000",
                "prior_status": "review",
                "decision": "approve",
                "tasks": ["T-1000"],
            }
        },
        actor="agent-spec",
    )
    assert result["status"] == "accepted"

    verify = service.verify()
    assert verify["verify_status"] == "ok"


# ---------------------------------------------------------------------------
# esaa process (inbox)
# ---------------------------------------------------------------------------


def test_process_inbox_accepted(contract_bundle: Path) -> None:
    """Process picks up files from inbox and applies them."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    inbox = contract_bundle / ".roadmap" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    payload = {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}}
    (inbox / "agent-spec__T-1000.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = service.process()
    assert result["processed"] == 1
    assert result["accepted"] == 1
    assert result["rejected"] == 0

    assert not (inbox / "agent-spec__T-1000.json").exists()
    assert (inbox / "done" / "agent-spec__T-1000.json").exists()


def test_process_inbox_rejected_moved(contract_bundle: Path) -> None:
    """Invalid submissions are moved to rejected/."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    inbox = contract_bundle / ".roadmap" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    payload = {"activity_event": {"action": "claim", "task_id": "T-9999", "prior_status": "todo"}}
    (inbox / "agent-spec__T-9999.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = service.process()
    assert result["processed"] == 1
    assert result["rejected"] == 1
    assert not (inbox / "agent-spec__T-9999.json").exists()
    assert (inbox / "rejected" / "agent-spec__T-9999.json").exists()


def test_process_inbox_without_actor_prefix(contract_bundle: Path) -> None:
    """Files without actor__ prefix use default actor."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    inbox = contract_bundle / ".roadmap" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    payload = {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}}
    (inbox / "T-1000.json").write_text(json.dumps(payload), encoding="utf-8")

    result = service.process()
    assert result["accepted"] == 1

    events = parse_event_store(contract_bundle)
    claim_events = [e for e in events if e["action"] == "claim"]
    assert claim_events[0]["actor"] == "agent-external"


def test_process_empty_inbox(contract_bundle: Path) -> None:
    """Process on empty/missing inbox returns zero counts."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    result = service.process()
    assert result["processed"] == 0
    assert result["accepted"] == 0


def test_process_dry_run(contract_bundle: Path) -> None:
    """Process dry run validates but does not move files."""
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    inbox = contract_bundle / ".roadmap" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    payload = {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}}
    (inbox / "agent-spec__T-1000.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    events_before = parse_event_store(contract_bundle)
    result = service.process(dry_run=True)
    assert result["accepted"] == 1
    events_after = parse_event_store(contract_bundle)
    assert len(events_after) == len(events_before)
    assert (inbox / "agent-spec__T-1000.json").exists()
