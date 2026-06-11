from __future__ import annotations

import json
from pathlib import Path

import yaml

from esaa.dispatch import build_minimal_context
from esaa.service import build_dispatch_context

ROOT = Path(__file__).resolve().parents[1]


def _schema() -> dict:
    return json.loads((ROOT / ".roadmap/agent_result.schema.json").read_text(encoding="utf-8"))


def _contract() -> dict:
    return yaml.safe_load((ROOT / ".roadmap/AGENT_CONTRACT.yaml").read_text(encoding="utf-8"))


def _roadmap() -> dict:
    return {
        "meta": {"master_correlation_id": "MC-1", "run": {"run_id": "RUN-1"}},
        "project": {"name": "cache-order"},
        "tasks": [
            {
                "task_id": "DEP-1",
                "task_kind": "spec",
                "status": "done",
                "title": "Dependency",
                "outputs": {"files": ["docs/spec/DEP-1.md"]},
            }
        ],
    }


def _task(task_id: str, status: str, *, depends_on: list[str] | None = None) -> dict:
    task = {
        "task_id": task_id,
        "task_kind": "impl",
        "status": status,
        "title": f"Task {task_id}",
        "description": f"Implement {task_id}",
        "depends_on": depends_on or [],
        "targets": ["impl-core"],
        "outputs": {"files": [f"src/{task_id}.txt"]},
    }
    if status == "review":
        task["verification"] = {"checks": ["ok"]}
    return task


def _lessons() -> list[dict]:
    return [
        {
            "lesson_id": "LES-CACHE",
            "status": "active",
            "scope": {"task_kinds": ["impl"]},
            "enforcement": {"mode": "reject", "applies_to": "output_contract"},
            "rule": "cache order",
        }
    ]


def test_minimal_context_orders_static_keys_before_task_by_status() -> None:
    roadmap = _roadmap()
    contract = _contract()
    schema = _schema()

    todo = build_minimal_context(roadmap, _task("T-1", "todo"), contract, schema, _lessons(), [])
    complete = build_minimal_context(
        roadmap,
        _task("T-2", "in_progress", depends_on=["DEP-1"]),
        contract,
        schema,
        _lessons(),
        [{"issue_id": "ISS-1", "status": "open", "baseline_id": "B-1"}],
    )
    review = build_minimal_context(roadmap, _task("T-3", "review"), contract, schema, _lessons(), [])

    assert list(todo) == [
        "expected_action",
        "allowed_actions",
        "schema_slice",
        "lessons",
        "task",
        "correlation",
    ]
    assert list(complete) == [
        "expected_action",
        "allowed_actions",
        "schema_slice",
        "boundaries",
        "lessons",
        "dep_interfaces",
        "task",
        "issues",
        "correlation",
    ]
    assert list(review) == [
        "expected_action",
        "allowed_actions",
        "schema_slice",
        "lessons",
        "task",
        "completed_verification",
        "correlation",
    ]


def test_minimal_context_static_prefix_is_byte_identical_until_task() -> None:
    roadmap = _roadmap()
    contract = _contract()
    schema = _schema()
    first = build_minimal_context(roadmap, _task("T-A", "in_progress"), contract, schema, _lessons(), [])
    second = build_minimal_context(roadmap, _task("T-B", "in_progress"), contract, schema, _lessons(), [])

    first_json = json.dumps(first, ensure_ascii=False)
    second_json = json.dumps(second, ensure_ascii=False)
    first_prefix = first_json[: first_json.index('"task"')]
    second_prefix = second_json[: second_json.index('"task"')]

    assert first_prefix == second_prefix


def test_legacy_dispatch_context_keeps_volatile_task_after_static_context() -> None:
    context = build_dispatch_context(_roadmap(), _task("T-LEG", "todo"), _contract())

    assert list(context) == ["boundaries", "context_pack", "task", "correlation"]
