from __future__ import annotations

import json
from pathlib import Path
from esaa.service import ESAAService
from esaa.store import parse_event_store


def test_hotfix_lifecycle_emits_issue_resolve_after_hotfix_review(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    service.claim_task("T-1000", actor="agent-spec")
    service.complete_task(
        "T-1000",
        actor="agent-spec",
        checks=["baseline"],
        file_updates=[{"path": "docs/T-1000.md", "content": "# T-1000\n"}],
    )
    service.review_task("T-1000", actor="agent-spec", decision="approve")

    service.report_issue(
        "T-1000",
        actor="agent-qa",
        issue_id="ISS-HOTFIX",
        severity="medium",
        title="Done task needs hotfix path",
        symptom="hotfix workflow must be exercised against an immutable done task",
        repro_steps=["run hotfix lifecycle test"],
        fixes="T-1000",
    )
    hotfix_task_id = "HF-ISS-HOTFIX"
    service.claim_task(hotfix_task_id, actor="agent-hotfix")
    service.complete_task(
        hotfix_task_id,
        actor="agent-hotfix",
        checks=["unit", "regression"],
        file_updates=[{"path": "src/hotfix/HF-ISS-HOTFIX.txt", "content": "hotfix\n"}],
        issue_id="ISS-HOTFIX",
        fixes="T-1000",
    )
    service.review_task(hotfix_task_id, actor="agent-hotfix", decision="approve")

    events = parse_event_store(contract_bundle)
    actions = [event["action"] for event in events]
    assert "issue.report" in actions
    assert "hotfix.create" in actions
    assert "issue.resolve" in actions

    service.project()
    issues_view = json.loads((contract_bundle / ".roadmap" / "issues.json").read_text(encoding="utf-8"))
    assert issues_view["issues"][0]["issue_id"] == "ISS-HOTFIX"
    assert issues_view["issues"][0]["status"] == "resolved"
    assert service.verify()["verify_status"] == "ok"
