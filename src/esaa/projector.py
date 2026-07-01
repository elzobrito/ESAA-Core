from __future__ import annotations

from copy import deepcopy
from typing import Any

from .compat import normalize_legacy_verify_status
from .constants import ESAA_VERSION, SCHEMA_VERSION
from .errors import ESAAError
from .state_machine import (
    REJECT_IMMUTABLE_DONE,
    REJECT_LOCK,
    REJECT_MISSING_CLAIM,
    REJECT_WORKFLOW_GATE,
    classify_transition,
)
from .utils import sha256_hex, utc_now_iso
from .validator import validate_g07_review_mode, validate_g07_task_create_payload


def _new_task(payload: dict[str, Any]) -> dict[str, Any]:
    description = payload.get("description", payload["title"])
    if not isinstance(description, str) or not description.strip():
        description = payload["title"]

    task = {
        "task_id": payload["task_id"],
        "task_kind": payload["task_kind"],
        "title": payload["title"],
        "description": description,
        "status": "todo",
        "depends_on": list(payload.get("depends_on", [])),
        "targets": list(payload.get("targets", [])),
        "outputs": payload.get("outputs", {"files": []}),
        "immutability": {"done_is_immutable": True},
    }
    if payload.get("is_hotfix"):
        task["is_hotfix"] = True
        for field in ("issue_id", "fixes", "scope_patch", "required_verification", "baseline_id"):
            if field in payload:
                task[field] = deepcopy(payload[field])
    if payload.get("boundary_grant"):
        task["boundary_grant"] = deepcopy(payload["boundary_grant"])
    for field in ("task_type", "acceptance_criteria", "required_review_mode", "supersedes"):
        if field in payload:
            task[field] = deepcopy(payload[field])
    if payload.get("plugin"):
        task["plugin"] = deepcopy(payload["plugin"])
    return task


def _index_counts(tasks: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for task in tasks:
        value = str(task.get(key, "unknown"))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda item: item[0]))


def compute_projection_hash(roadmap: dict[str, Any]) -> str:
    payload = {
        "schema_version": roadmap["meta"]["schema_version"],
        "project": roadmap["project"],
        "tasks": roadmap["tasks"],
        "indexes": roadmap["indexes"],
    }
    return sha256_hex(payload)


def _empty_state(project_name: str) -> dict[str, Any]:
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "esaa_version": ESAA_VERSION,
            "immutable_done": True,
            "master_correlation_id": None,
            "run": {
                "run_id": None,
                "status": "initialized",
                "last_event_seq": 0,
                "projection_hash_sha256": "",
                "verify_status": "unknown",
            },
            "updated_at": utc_now_iso(),
        },
        "project": {"name": project_name, "audit_scope": ".roadmap/"},
        "tasks": [],
        "indexes": {"by_status": {}, "by_kind": {}},
        "_issues": {},
        "_lessons": [],
    }


def _task_by_id(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in state["tasks"]:
        if task["task_id"] == task_id:
            return task
    raise ESAAError("TASK_NOT_FOUND", f"task_id not found: {task_id}")


def _existing_task_ids(state: dict[str, Any]) -> set[str]:
    return {task["task_id"] for task in state["tasks"]}


def _derive_superseded_by(state: dict[str, Any], task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    for superseded_task_id in task.get("supersedes", []):
        superseded_task = _task_by_id(state, superseded_task_id)
        superseded_by = superseded_task.setdefault("superseded_by", [])
        if task_id not in superseded_by:
            superseded_by.append(task_id)


def _ensure_owner(task: dict[str, Any], actor: str) -> None:
    owner = task.get("assigned_to")
    if owner != actor:
        raise ESAAError(REJECT_LOCK, f"actor {actor} != lock owner {owner}")


def _check_transition(task: dict[str, Any], action: str) -> None:
    """Aplica a maquina de estado canonica (RF01) com reject_codes do contrato."""
    ok, code = classify_transition(task["status"], action)
    if not ok:
        raise ESAAError(code, f"{action} invalid for status={task['status']}")


def _apply_claim(state: dict[str, Any], event: dict[str, Any]) -> None:
    task = _task_by_id(state, event["payload"]["task_id"])
    _check_transition(task, "claim")
    if task.get("assigned_to"):
        raise ESAAError(REJECT_LOCK, "task already locked")
    task["status"] = "in_progress"
    task["assigned_to"] = event["actor"]
    task["started_at"] = event["ts"]


def _apply_complete(state: dict[str, Any], event: dict[str, Any]) -> None:
    task = _task_by_id(state, event["payload"]["task_id"])
    _check_transition(task, "complete")
    _ensure_owner(task, event["actor"])
    task["status"] = "review"
    verification = event["payload"].get("verification")
    if verification:
        task["verification"] = deepcopy(verification)
    if "issue_id" in event["payload"]:
        task["issue_id"] = event["payload"]["issue_id"]
    if "fixes" in event["payload"]:
        task["fixes"] = event["payload"]["fixes"]


def _apply_review(state: dict[str, Any], event: dict[str, Any]) -> None:
    task = _task_by_id(state, event["payload"]["task_id"])
    decision = event["payload"].get("decision")
    _check_transition(task, "review")
    validate_g07_review_mode(task, event["payload"])
    # FIX-1807: review autoriza-se por owner (legado) ou por role qa/orchestrator.
    # O service injeta '_reviewer_role' no payload apos resolver runtime_policy.
    reviewer_role = event.get("reviewer_role") or event["payload"].get("_reviewer_role")
    if reviewer_role not in {"qa", "orchestrator"}:
        _ensure_owner(task, event["actor"])
    if decision == "approve":
        task["status"] = "done"
        task["completed_at"] = event["ts"]
    elif decision == "request_changes":
        task["status"] = "in_progress"
    else:
        raise ESAAError(REJECT_WORKFLOW_GATE, f"review decision invalid: {decision}")


def _apply_issue_report(state: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event["payload"]
    issue_id = payload["issue_id"]
    issue = state["_issues"].setdefault(
        issue_id,
        {
            "issue_id": issue_id,
            "status": "open",
            "severity": payload.get("severity", "medium"),
            "title": payload.get("title", issue_id),
            "baseline_id": payload.get("affected", {}).get("baseline_id"),
            "affected": deepcopy(payload.get("affected", {})),
            "evidence": deepcopy(payload.get("evidence", {})),
            "resolution": None,
            "links": {
                "reported_by_task_id": payload.get("task_id"),
                "fixes_task_id": payload.get("fixes"),
                "hotfix_task_id": None,
            },
            "timeline": {
                "created_event_seq": event["event_seq"],
                "resolved_event_seq": None,
            },
        },
    )
    issue["status"] = "open"
    issue["severity"] = payload.get("severity", issue["severity"])
    issue["title"] = payload.get("title", issue["title"])
    issue["evidence"] = deepcopy(payload.get("evidence", issue.get("evidence", {})))

    if payload.get("category") == "process" and payload.get("subtype") == "lesson" and "lesson" in payload:
        lesson_payload = deepcopy(payload["lesson"])
        lesson_id = f"LES-{len(state['_lessons']) + 1:04d}"
        state["_lessons"].append(
            {
                "lesson_id": lesson_id,
                "status": "active",
                "created_at": event["ts"],
                "title": payload.get("title", lesson_id),
                "mistake": lesson_payload["mistake"],
                "rule": lesson_payload["rule"],
                "scope": lesson_payload["scope"],
                "enforcement": lesson_payload["enforcement"],
                "source_refs": [{"task_id": payload.get("task_id"), "event_id": event["event_id"]}],
            }
        )


def _apply_hotfix_create(state: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event["payload"]
    task_id = payload["task_id"]
    for task in state["tasks"]:
        if task["task_id"] == task_id:
            raise ESAAError("DUPLICATE_TASK", f"task already exists: {task_id}")
    state["tasks"].append(_new_task(payload))
    issue_id = payload.get("issue_id")
    if issue_id and issue_id in state["_issues"]:
        state["_issues"][issue_id]["links"]["hotfix_task_id"] = task_id


def _apply_issue_resolve(state: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event["payload"]
    issue_id = payload["issue_id"]
    issue = state["_issues"].get(issue_id)
    if not issue:
        raise ESAAError("ISSUE_NOT_FOUND", f"issue not found: {issue_id}")
    issue["status"] = "resolved"
    issue["resolution"] = deepcopy(payload.get("resolution", {}))
    issue["timeline"]["resolved_event_seq"] = event["event_seq"]


def _apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    action = event["action"]
    payload = event["payload"]

    if action == "run.start":
        state["meta"]["master_correlation_id"] = payload.get("master_correlation_id")
        state["meta"]["run"]["run_id"] = payload.get("run_id", state["meta"]["run"]["run_id"])
        state["meta"]["run"]["status"] = payload.get("status", "initialized")
        if payload.get("project_name"):
            state["project"]["name"] = payload["project_name"]
        if payload.get("audit_scope"):
            state["project"]["audit_scope"] = payload["audit_scope"]
    elif action == "run.end":
        state["meta"]["run"]["status"] = payload.get("status", "success")
    elif action == "task.create":
        validate_g07_task_create_payload(payload, _existing_task_ids(state))
        task = _new_task(payload)
        state["tasks"].append(task)
        _derive_superseded_by(state, task)
    elif action == "claim":
        _apply_claim(state, event)
    elif action == "complete":
        _apply_complete(state, event)
    elif action == "review":
        _apply_review(state, event)
    elif action == "issue.report":
        _apply_issue_report(state, event)
    elif action == "hotfix.create":
        _apply_hotfix_create(state, event)
    elif action == "issue.resolve":
        _apply_issue_resolve(state, event)
    elif action == "verify.ok":
        state["meta"]["run"]["verify_status"] = "ok"
    elif action == "verify.fail":
        state["meta"]["run"]["verify_status"] = payload.get("verify_status", "mismatch")
    elif action == "orchestrator.view.mutate":
        # R1-fix: um view.mutate pode registrar lessons de forma reconstruivel
        # por replay. Quando o payload carrega 'lessons', a projecao passa a
        # deriva-las do event store (e nao de edicao manual do read model).
        if isinstance(payload.get("lessons"), list):
            state["_lessons"] = deepcopy(payload["lessons"])
    elif action in {
        "output.rejected",
        "orchestrator.file.write",
        "runner.metrics",
        "chain.anchor",
        "verify.start",
        "plugin.install",
        "plugin.remove",
        "plugin.update",
        "roadmap.activate",
        "roadmap.pause",
        "roadmap.resume",
        "roadmap.deactivate",
    }:
        pass
    else:
        raise ESAAError("UNKNOWN_ACTION", f"unknown action: {action}")

    state["meta"]["run"]["last_event_seq"] = event["event_seq"]
    state["meta"]["updated_at"] = event["ts"]


def materialize(
    events: list[dict[str, Any]], project_name: str = "esaa-core"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = _empty_state(project_name=project_name)
    for event in events:
        _apply_event(state, event)

    state["indexes"]["by_status"] = _index_counts(state["tasks"], "status")
    state["indexes"]["by_kind"] = _index_counts(state["tasks"], "task_kind")

    roadmap = {
        "meta": deepcopy(state["meta"]),
        "project": deepcopy(state["project"]),
        "tasks": deepcopy(state["tasks"]),
        "indexes": deepcopy(state["indexes"]),
    }
    roadmap["meta"]["run"]["verify_status"] = normalize_legacy_verify_status(
        roadmap["meta"]["run"]["verify_status"]
    )
    roadmap["meta"]["run"]["projection_hash_sha256"] = compute_projection_hash(roadmap)

    issues = sorted(state["_issues"].values(), key=lambda issue: issue["issue_id"])
    open_by_baseline: dict[str, list[str]] = {}
    for issue in issues:
        if issue["status"] != "open":
            continue
        baseline = issue.get("baseline_id") or "unknown"
        open_by_baseline.setdefault(baseline, []).append(issue["issue_id"])

    issues_view = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "esaa_version": ESAA_VERSION,
            "generated_by": "esaa.project",
            "source_event_store": ".roadmap/activity.jsonl",
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "updated_at": roadmap["meta"]["updated_at"],
        },
        "issues": issues,
        "indexes": {"open_by_baseline": dict(sorted(open_by_baseline.items(), key=lambda item: item[0]))},
    }

    by_task_kind: dict[str, list[str]] = {}
    by_enforcement: dict[str, list[str]] = {}
    lessons = deepcopy(state["_lessons"])
    for lesson in lessons:
        for kind in lesson["scope"].get("task_kinds", []):
            by_task_kind.setdefault(kind, []).append(lesson["lesson_id"])
        applies_to = lesson["enforcement"].get("applies_to") or lesson["enforcement"].get("mode", "unknown")
        by_enforcement.setdefault(applies_to, []).append(lesson["lesson_id"])

    lessons_view = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "esaa_version": ESAA_VERSION,
            "generated_by": "esaa.project",
            "source_event_store": ".roadmap/activity.jsonl",
            "updated_at": roadmap["meta"]["updated_at"],
        },
        "lessons": lessons,
        "indexes": {
            "by_task_kind": dict(sorted(by_task_kind.items(), key=lambda item: item[0])),
            "by_enforcement_applies_to": dict(sorted(by_enforcement.items(), key=lambda item: item[0])),
        },
    }
    return roadmap, issues_view, lessons_view
