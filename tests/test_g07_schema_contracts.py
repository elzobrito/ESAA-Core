from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_template_schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "src" / "esaa" / "templates" / name).read_text(encoding="utf-8"))


def _assert_valid(schema: dict, payload: dict) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    assert errors == []


def _assert_invalid(schema: dict, payload: dict, expected_path: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    assert errors
    rendered_paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in rendered_paths


def _minimal_roadmap() -> dict:
    return {
        "meta": {
            "schema_version": "0.4.1",
            "esaa_version": "0.4.1",
            "immutable_done": True,
            "master_correlation_id": None,
            "run": {
                "run_id": None,
                "status": "initialized",
                "last_event_seq": 0,
                "projection_hash_sha256": "0" * 64,
                "verify_status": "ok",
            },
            "updated_at": "2026-07-01T00:00:00Z",
        },
        "project": {"name": "test", "audit_scope": ".roadmap/"},
        "tasks": [
            {
                "task_id": "T-OLD",
                "task_kind": "spec",
                "title": "Legacy task",
                "description": "A task without G07 fields remains valid.",
                "status": "todo",
                "depends_on": [],
                "targets": ["docs/spec/legacy.md"],
                "outputs": {"files": ["docs/spec/legacy.md"]},
                "immutability": {"done_is_immutable": True},
            }
        ],
        "indexes": {"by_status": {"todo": 1}, "by_kind": {"spec": 1}},
    }


def test_legacy_roadmap_without_g07_task_fields_remains_valid() -> None:
    schema = _load_template_schema("roadmap.schema.json")

    _assert_valid(schema, _minimal_roadmap())


def test_roadmap_schema_accepts_optional_g07_task_fields() -> None:
    schema = _load_template_schema("roadmap.schema.json")
    roadmap = _minimal_roadmap()
    roadmap["tasks"][0].update(
        {
            "task_type": "governance",
            "acceptance_criteria": [
                "The spec defines optional task fields.",
                "The spec defines validation timing before append.",
            ],
            "required_review_mode": "governance",
            "supersedes": ["T-PREV"],
            "superseded_by": ["T-NEXT"],
        }
    )

    _assert_valid(schema, roadmap)


def test_roadmap_schema_rejects_invalid_g07_enums_and_duplicate_supersedes() -> None:
    schema = _load_template_schema("roadmap.schema.json")
    roadmap = _minimal_roadmap()

    invalid_task_type = copy.deepcopy(roadmap)
    invalid_task_type["tasks"][0]["task_type"] = "research"
    _assert_invalid(schema, invalid_task_type, "tasks.0.task_type")

    invalid_review_mode = copy.deepcopy(roadmap)
    invalid_review_mode["tasks"][0]["required_review_mode"] = "audit"
    _assert_invalid(schema, invalid_review_mode, "tasks.0.required_review_mode")

    duplicate_supersedes = copy.deepcopy(roadmap)
    duplicate_supersedes["tasks"][0]["supersedes"] = ["T-PREV", "T-PREV"]
    _assert_invalid(schema, duplicate_supersedes, "tasks.0.supersedes")


def test_agent_result_schema_accepts_optional_review_mode_on_review() -> None:
    schema = _load_template_schema("agent_result.schema.json")
    payload = {
        "activity_event": {
            "action": "review",
            "task_id": "T-G07",
            "prior_status": "review",
            "decision": "approve",
            "review_mode": "governance",
            "tasks": ["T-G07"],
        }
    }

    _assert_valid(schema, payload)


def test_agent_result_schema_rejects_invalid_review_mode_enum() -> None:
    schema = _load_template_schema("agent_result.schema.json")
    payload = {
        "activity_event": {
            "action": "review",
            "task_id": "T-G07",
            "prior_status": "review",
            "decision": "approve",
            "review_mode": "audit",
            "tasks": ["T-G07"],
        }
    }

    _assert_invalid(schema, payload, "activity_event.review_mode")
