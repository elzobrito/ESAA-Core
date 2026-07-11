"""FIX-1811-QA — Hotfix create validation (via validate_hotfix_request)."""
from __future__ import annotations

from pathlib import Path

import pytest

from esaa.service import ESAAService, validate_hotfix_request
from esaa.store import parse_event_store


def _drive_to_done(svc: ESAAService, task_id: str = "T-1000", actor: str = "agent-spec") -> None:
    svc.submit({"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}}, actor=actor)
    kind_map = {"T-1000": "spec", "T-1010": "impl", "T-1020": "qa"}
    out = {"T-1000": "docs/spec/T-1000.md", "T-1010": "src/T-1010.txt", "T-1020": "docs/qa/T-1020.md"}
    svc.submit({"activity_event": {
        "action": "complete", "task_id": task_id, "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": out[task_id], "content": "#\n"}]}, actor=actor)
    svc.submit({"activity_event": {
        "action": "review", "task_id": task_id, "prior_status": "review",
        "decision": "approve", "tasks": [task_id],
    }}, actor=actor)


def test_validate_target_not_found(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    ok, code, msg = validate_hotfix_request(events, {
        "issue_id": "ISS-Z", "fixes": "T-NONEXISTENT",
        "scope_patch": ["src/hotfix/"],
    })
    assert ok is False
    assert code == "HOTFIX_TARGET_NOT_FOUND"


def test_validate_target_not_done(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    # T-1000 ainda esta em todo, com immutability:done_is_immutable=True
    ok, code, _ = validate_hotfix_request(events, {
        "issue_id": "ISS-Z", "fixes": "T-1000",
        "scope_patch": ["src/hotfix/"],
    })
    assert ok is False
    assert code == "HOTFIX_TARGET_NOT_DONE"


def test_validate_scope_invalid_empty(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc, "T-1000")
    events = parse_event_store(contract_bundle)
    ok, code, _ = validate_hotfix_request(events, {
        "issue_id": "ISS-Z", "fixes": "T-1000",
        "scope_patch": [],
    })
    assert ok is False
    assert code == "HOTFIX_SCOPE_INVALID"


def test_validate_scope_missing_uses_default_for_agent_issue(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc, "T-1000")
    svc.report_issue(
        "T-1000",
        actor="agent-qa",
        issue_id="ISS-Z",
        severity="high",
        title="Agent reported done-task defect",
        symptom="post-done defect",
        repro_steps=["inspect T-1000"],
    )
    events = parse_event_store(contract_bundle)
    ok, code, _ = validate_hotfix_request(events, {
        "issue_id": "ISS-Z", "fixes": "T-1000",
    })
    assert ok is True
    assert code is None


def test_validate_valid_hotfix_for_done_open_issue(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc, "T-1000")
    svc.report_issue(
        "T-1000",
        actor="agent-qa",
        issue_id="ISS-NEW",
        severity="high",
        title="Valid hotfix issue",
        symptom="post-done defect",
        repro_steps=["inspect T-1000"],
    )
    events = parse_event_store(contract_bundle)
    ok, code, _ = validate_hotfix_request(events, {
        "issue_id": "ISS-NEW", "fixes": "T-1000",
        "scope_patch": ["src/hotfix/"],
    })
    assert ok is True
    assert code is None


def test_validate_missing_issue_id(contract_bundle: Path) -> None:
    events = []
    ok, code, _ = validate_hotfix_request(events, {"fixes": "T-1"})
    assert ok is False
    assert code == "HOTFIX_ISSUE_NOT_FOUND"


def test_validate_missing_fixes(contract_bundle: Path) -> None:
    events = []
    ok, code, _ = validate_hotfix_request(events, {"issue_id": "ISS-1"})
    assert ok is False
    assert code == "HOTFIX_TARGET_NOT_FOUND"
