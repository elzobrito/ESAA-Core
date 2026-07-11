"""FIX-1810-QA — issue.report preserva prior_status=done sobre tarefa imutavel."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from esaa.errors import ESAAError
from esaa.service import ESAAService


def _load_schema(contract_bundle: Path) -> dict:
    return json.loads((contract_bundle / ".roadmap" / "agent_result.schema.json").read_text(encoding="utf-8"))


def test_schema_allows_done_in_prior_status_for_issue_report(contract_bundle: Path) -> None:
    """Schema deve aceitar action=issue.report com prior_status=done."""
    schema = _load_schema(contract_bundle)
    validator = Draft202012Validator(schema)
    output = {
        "activity_event": {
            "action": "issue.report",
            "task_id": "T-1000",
            "prior_status": "done",
            "issue_id": "ISS-1",
            "severity": "high",
            "title": "Bug post-done",
            "evidence": {"symptom": "fail", "repro_steps": ["s1"]},
        }
    }
    errors = list(validator.iter_errors(output))
    assert errors == []


def test_schema_rejects_done_for_claim(contract_bundle: Path) -> None:
    """Schema deve rejeitar claim com prior_status=done (allOf const violation)."""
    schema = _load_schema(contract_bundle)
    validator = Draft202012Validator(schema)
    output = {
        "activity_event": {
            "action": "claim",
            "task_id": "T-1000",
            "prior_status": "done",
        }
    }
    errors = list(validator.iter_errors(output))
    # claim exige prior_status="todo" (const), entao errors > 0
    assert len(errors) >= 1


def test_schema_rejects_done_for_complete(contract_bundle: Path) -> None:
    schema = _load_schema(contract_bundle)
    validator = Draft202012Validator(schema)
    output = {
        "activity_event": {
            "action": "complete",
            "task_id": "T-1000",
            "prior_status": "done",
            "verification": {"checks": ["x"]},
        }
    }
    errors = list(validator.iter_errors(output))
    assert len(errors) >= 1


def test_issue_report_on_done_preserves_status(contract_bundle: Path) -> None:
    """issue.report sobre done aceita; task continua done."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit({"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "complete", "task_id": "T-1000", "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "review", "task_id": "T-1000", "prior_status": "review",
        "decision": "approve", "tasks": ["T-1000"],
    }}, actor="agent-spec")

    # T-1000 agora esta done. issue.report com prior_status=done
    r = svc.submit({"activity_event": {
        "action": "issue.report", "task_id": "T-1000", "prior_status": "done",
        "issue_id": "ISS-POST-DONE", "severity": "medium",
        "title": "Issue on done task",
        "evidence": {"symptom": "edge case", "repro_steps": ["step 1"]},
    }}, actor="agent-spec")
    assert r["status"] == "accepted"
    # Status segue done
    import json as _json
    roadmap = _json.loads((contract_bundle / ".roadmap" / "roadmap.json").read_text(encoding="utf-8"))
    t = next(t for t in roadmap["tasks"] if t["task_id"] == "T-1000")
    assert t["status"] == "done"


def test_claim_on_done_rejected(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    # Drive T-1000 to done
    svc.submit({"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "complete", "task_id": "T-1000", "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "review", "task_id": "T-1000", "prior_status": "review",
        "decision": "approve", "tasks": ["T-1000"],
    }}, actor="agent-spec")
    # Tentar claim sobre done -> rejeitado
    with pytest.raises(ESAAError) as exc:
        svc.submit({"activity_event": {
            "action": "claim", "task_id": "T-1000", "prior_status": "todo",
        }}, actor="agent-spec")
    # Pode ser PRIOR_STATUS_MISMATCH (prior_status=todo, real=done) OU IMMUTABLE_DONE_VIOLATION
    assert exc.value.code in {"IMMUTABLE_DONE_VIOLATION", "PRIOR_STATUS_MISMATCH"}
