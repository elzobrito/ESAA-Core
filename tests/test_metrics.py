from __future__ import annotations

from esaa.metrics import compute_metrics
from esaa.service import make_event


def test_compute_metrics_counts_actions_rejections_gates_and_tasks() -> None:
    events = [
        make_event(1, "orchestrator", "run.start", {"run_id": "RUN-M", "status": "initialized"}),
        make_event(
            2,
            "orchestrator",
            "task.create",
            {
                "task_id": "T-1",
                "task_kind": "spec",
                "title": "Task 1",
                "depends_on": [],
                "outputs": {"files": ["docs/spec/T-1.md"]},
            },
        ),
        make_event(3, "agent-spec", "claim", {"action": "claim", "task_id": "T-1", "prior_status": "todo"}),
        make_event(
            4,
            "orchestrator",
            "output.rejected",
            {
                "task_id": "T-1",
                "error_code": "MISSING_VERIFICATION",
                "source_action": "complete",
            },
        ),
        make_event(
            5,
            "orchestrator",
            "output.rejected",
            {
                "task_id": "T-1",
                "error_code": "LOCK_VIOLATION",
                "source_action": "complete",
            },
        ),
        make_event(
            6,
            "agent-spec",
            "complete",
            {
                "action": "complete",
                "task_id": "T-1",
                "prior_status": "in_progress",
                "verification": {"checks": ["ok"]},
            },
        ),
        make_event(
            7,
            "agent-spec",
            "review",
            {
                "action": "review",
                "task_id": "T-1",
                "prior_status": "review",
                "decision": "approve",
                "tasks": ["T-1"],
            },
        ),
    ]

    metrics = compute_metrics(events)

    assert metrics["events_total"] == 7
    assert metrics["events_by_action"]["output.rejected"] == 2
    assert metrics["output_rejected_by_code"] == {
        "LOCK_VIOLATION": 1,
        "MISSING_VERIFICATION": 1,
    }
    assert metrics["workflow_gate_hits"] == {"WG-002": 1, "WG-004": 1}
    assert metrics["attempts_total"] == 2
    assert metrics["attempts_by_task"] == {"T-1": 2}
    assert metrics["rejection_rate"] == 2 / 7
    assert metrics["tasks"] == {"done": 1, "total": 1}
    assert metrics["run_status"] == "initialized"
