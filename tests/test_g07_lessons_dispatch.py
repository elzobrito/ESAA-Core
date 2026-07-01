from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from esaa.dispatch import build_minimal_context, filter_lessons
from esaa.events import make_event
from esaa.projector import materialize


REPO_ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "src" / "esaa" / "templates" / name).read_text(encoding="utf-8"))


def _assert_schema_valid(schema: dict, payload: dict) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    assert errors == []


def _lesson(
    lesson_id: str,
    *,
    status: str = "active",
    scope: dict | None = None,
    enforcement: dict | None = None,
) -> dict:
    return {
        "lesson_id": lesson_id,
        "status": status,
        "created_at": "2026-07-01T00:00:00Z",
        "title": lesson_id,
        "mistake": "Observed mistake",
        "rule": f"Rule for {lesson_id}",
        "scope": scope or {"task_kinds": ["spec"]},
        "enforcement": enforcement or {"mode": "warn"},
        "source_refs": [{"type": "task", "id": "T-1"}],
    }


def _task(**overrides) -> dict:
    task = {
        "task_id": "T-1",
        "task_kind": "spec",
        "status": "in_progress",
        "title": "Task",
        "description": "Task description",
        "depends_on": [],
        "targets": ["docs/spec/g07.md"],
        "outputs": {"files": ["docs/spec/g07.md"]},
        "task_type": "governance",
        "required_review_mode": "governance",
        "acceptance_criteria": ["AC one"],
        "supersedes": ["T-0"],
        "superseded_by": ["T-2"],
    }
    task.update(overrides)
    return task


def test_lessons_schema_accepts_g07_shape_and_legacy_shape() -> None:
    schema = _schema("lessons.schema.json")
    payload = {
        "meta": {
            "schema_version": "0.4.1",
            "esaa_version": "0.4.1",
            "generated_by": "esaa.project",
            "source_event_store": ".roadmap/activity.jsonl",
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "lessons": [
            _lesson(
                "LES-0100",
                status="experimental",
                scope={"task_types": ["governance"], "paths": ["docs/spec/**"]},
                enforcement={"mode": "require_review_mode", "value": "governance"},
            ),
            _lesson(
                "LES-0001",
                scope={"task_kinds": ["spec", "impl", "qa"]},
                enforcement={"mode": "reject", "applies_to": "workflow_gate"},
            ),
        ],
        "indexes": {
            "by_task_kind": {"spec": ["LES-0001"]},
            "by_enforcement_applies_to": {"workflow_gate": ["LES-0001"]},
        },
    }

    _assert_schema_valid(schema, payload)


def test_filter_lessons_uses_or_within_dimensions_and_and_between_dimensions() -> None:
    task = _task()
    lessons = [
        _lesson(
            "LES-0100",
            scope={"task_types": ["governance", "audit"], "paths": ["docs/spec/**"]},
            enforcement={"mode": "require_review_mode", "value": "governance"},
        ),
        _lesson(
            "LES-0101",
            scope={"task_types": ["governance"], "paths": ["src/**"]},
        ),
        _lesson("LES-0102", status="experimental", scope={"task_kinds": ["spec"]}),
        _lesson("LES-0103", status="superseded", scope={"task_kinds": ["spec"]}),
    ]

    filtered = filter_lessons(lessons, task, "complete")

    assert [lesson["lesson_id"] for lesson in filtered] == ["LES-0100", "LES-0102"]
    assert filtered[1]["status"] == "experimental"


def test_dispatch_context_exposes_g07_task_fields() -> None:
    roadmap = {
        "meta": {"master_correlation_id": "CID-1"},
        "tasks": [_task()],
    }
    contract = {
        "boundaries": {
            "by_task_kind": {
                "spec": {
                    "read": ["docs/**"],
                    "write": ["docs/**"],
                    "forbidden_write": [".roadmap/**"],
                }
            }
        }
    }
    schema = _schema("agent_result.schema.json")

    context = build_minimal_context(
        roadmap,
        _task(),
        contract,
        schema,
        lessons=[_lesson("LES-0100", scope={"task_types": ["governance"]})],
        issues=[],
    )

    task_ctx = context["task"]
    assert task_ctx["task_type"] == "governance"
    assert task_ctx["acceptance_criteria"] == ["AC one"]
    assert task_ctx["required_review_mode"] == "governance"
    assert task_ctx["supersedes"] == ["T-0"]
    assert task_ctx["superseded_by"] == ["T-2"]
    assert context["lessons"][0]["lesson_id"] == "LES-0100"


def test_projector_accepts_g07_lesson_without_legacy_applies_to() -> None:
    lessons = [
        _lesson(
            "LES-0100",
            scope={"task_types": ["governance"]},
            enforcement={"mode": "require_review_mode", "value": "governance"},
        )
    ]
    events = [
        make_event(
            1,
            actor="orchestrator",
            action="orchestrator.view.mutate",
            payload={"target": "lessons", "change": "g07_test", "lessons": copy.deepcopy(lessons)},
        )
    ]

    _, _, lessons_view = materialize(events)

    assert lessons_view["lessons"] == lessons
    assert lessons_view["indexes"]["by_enforcement_applies_to"] == {
        "require_review_mode": ["LES-0100"]
    }
