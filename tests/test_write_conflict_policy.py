from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from esaa.adapters.base import AgentAdapter
from esaa.conflicts import conflict_between_sets, explain_conflict, normalize_write_set
from esaa.service import ESAAService, parallel_groups
from esaa.store import parse_event_store


class SharedWriteAdapter(AgentAdapter):
    agent_id = "agent-spec"

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def execute(self, dispatch_context: dict[str, Any]) -> dict[str, Any]:
        task = dispatch_context["task"]
        if task["status"] == "todo":
            return {
                "activity_event": {
                    "action": "claim",
                    "task_id": task["task_id"],
                    "prior_status": "todo",
                }
            }
        if task["status"] == "in_progress":
            return {
                "activity_event": {
                    "action": "complete",
                    "task_id": task["task_id"],
                    "prior_status": "in_progress",
                    "verification": {"checks": ["shared-write-check"]},
                },
                "file_updates": [{"path": "docs/spec/shared.md", "content": task["task_id"]}],
            }
        return {
            "activity_event": {
                "action": "review",
                "task_id": task["task_id"],
                "prior_status": "review",
                "decision": "approve",
                "tasks": [task["task_id"]],
            }
        }


def _write_plugin(root: Path, tasks: list[dict[str, Any]]) -> None:
    (root / ".roadmap" / "roadmap.conflicts.json").write_text(
        json.dumps({"project": {"name": "conflicts"}, "tasks": tasks}),
        encoding="utf-8",
    )


def test_conflict_helpers_detect_exact_and_directory_prefix() -> None:
    assert normalize_write_set(["docs/spec/a.md", "docs/spec/"]) == ["docs/spec/", "docs/spec/a.md"]
    assert conflict_between_sets(["docs/spec/a.md"], ["docs/spec/a.md"])
    assert conflict_between_sets(["docs/spec/"], ["docs/spec/a.md"])
    assert not conflict_between_sets(["docs/spec/a.md"], ["docs/qa/a.md"])
    assert explain_conflict(["docs/spec/"], ["docs/spec/a.md"])["type"] == "prefix"


def test_parallel_groups_separate_planned_write_conflicts(contract_bundle: Path) -> None:
    tasks = [
        {
            "task_id": "P-1",
            "task_kind": "spec",
            "title": "P1",
            "depends_on": [],
            "outputs": {"files": ["docs/spec/same.md"]},
        },
        {
            "task_id": "P-2",
            "task_kind": "spec",
            "title": "P2",
            "depends_on": [],
            "outputs": {"files": ["docs/spec/same.md"]},
        },
        {
            "task_id": "P-3",
            "task_kind": "spec",
            "title": "P3",
            "depends_on": [],
            "outputs": {"files": ["docs/qa/other.md"]},
        },
    ]

    assert parallel_groups(tasks) == [["P-1", "P-3"], ["P-2"]]


def test_parallel_complete_write_conflict_rejects_without_second_side_effect(contract_bundle: Path) -> None:
    _write_plugin(
        contract_bundle,
        [
            {
                "task_id": "P-1",
                "task_kind": "spec",
                "title": "P1",
                "depends_on": [],
                "outputs": {"files": ["docs/spec/p1.md"]},
            },
            {
                "task_id": "P-2",
                "task_kind": "spec",
                "title": "P2",
                "depends_on": [],
                "outputs": {"files": ["docs/spec/p2.md"]},
            },
        ],
    )
    service = ESAAService(contract_bundle, adapter=SharedWriteAdapter())
    service.init(force=True, with_demo_tasks=True)
    service.run(steps=1, parallel=2)

    result = service.run(steps=1, parallel=2)

    assert result["rejected"] == 1
    assert result["files_written"] == 1
    assert (contract_bundle / "docs/spec/shared.md").read_text(encoding="utf-8") == "P-1"
    rejected = [event for event in parse_event_store(contract_bundle) if event["action"] == "output.rejected"]
    assert rejected[-1]["payload"]["error_code"] == "WRITE_CONFLICT"
    assert service.verify()["verify_status"] == "ok"


def test_single_run_cross_iteration_write_conflict_rejects_second_write(contract_bundle: Path) -> None:
    _write_plugin(
        contract_bundle,
        [
            {
                "task_id": "P-1",
                "task_kind": "spec",
                "title": "P1",
                "depends_on": [],
                "outputs": {"files": ["docs/spec/p1.md"]},
            },
            {
                "task_id": "P-2",
                "task_kind": "spec",
                "title": "P2",
                "depends_on": ["P-1"],
                "outputs": {"files": ["docs/spec/p2.md"]},
            },
        ],
    )
    service = ESAAService(contract_bundle, adapter=SharedWriteAdapter())
    service.init(force=True, with_demo_tasks=True)

    result = service.run(steps=None, parallel=1)

    assert (contract_bundle / "docs/spec/shared.md").read_text(encoding="utf-8") == "P-1"
    rejected = [event for event in parse_event_store(contract_bundle) if event["action"] == "output.rejected"]
    assert any(event["payload"]["error_code"] == "WRITE_CONFLICT" for event in rejected)
    assert result["rejected"] >= 1
    assert service.verify()["verify_status"] == "ok"
