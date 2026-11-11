from __future__ import annotations

from pathlib import Path

from esaa.scenarios import run_hotfix_trace
from esaa.store import parse_event_store


def test_hotfix_trace_scenario_emits_full_ordered_flow(contract_bundle: Path) -> None:
    result = run_hotfix_trace(contract_bundle, issue_id="ISS-CMM5-HOTFIX")

    assert result["verify_status"] == "ok"
    assert result["issue_id"] == "ISS-CMM5-HOTFIX"
    assert result["hotfix_task_id"] == "HF-ISS-CMM5-HOTFIX"
    assert result["events_found"] == [
        "issue.report",
        "hotfix.create",
        "claim",
        "complete",
        "orchestrator.file.write",
        "review",
        "issue.resolve",
        "verify.start",
        "verify.ok",
    ]
    assert result["issues"][0]["status"] == "resolved"


def test_hotfix_trace_can_run_in_explicit_workspace(contract_bundle: Path) -> None:
    result = run_hotfix_trace(contract_bundle, target_root=contract_bundle, issue_id="ISS-CURRENT")

    events = parse_event_store(contract_bundle)
    assert result["workspace"] == str(contract_bundle)
    assert "issue.resolve" in [event["action"] for event in events]
    assert result["verify_status"] == "ok"
