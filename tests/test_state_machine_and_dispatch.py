"""Cobertura da maquina de estado canonica, slicing e RF07.

RF01: transicoes locais; RF02: IMMUTABLE_DONE_VIOLATION; RF03: request_changes;
RF04: slice_schema; RF05: dep_interfaces; RF06: filter_lessons/issues;
RF07: PRIOR_STATUS_MISMATCH.
"""
from __future__ import annotations

import json
from pathlib import Path

from esaa.dispatch import (
    build_minimal_context,
    dep_interfaces,
    filter_issues,
    filter_lessons,
    slice_schema,
)
from esaa.state_machine import (
    REJECT_IMMUTABLE_DONE,
    REJECT_LOCK,
    REJECT_MISSING_CLAIM,
    classify_transition,
    expected_action_for,
    is_terminal_completion,
    next_status,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_schema() -> dict:
    return json.loads((ROOT / ".roadmap/agent_result.schema.json").read_text(encoding="utf-8"))


def _load_contract() -> dict:
    import yaml
    return yaml.safe_load((ROOT / ".roadmap/AGENT_CONTRACT.yaml").read_text(encoding="utf-8"))


# --- Maquina de estado ------------------------------------------------------

def test_expected_action_per_status():
    assert expected_action_for("todo") == "claim"
    assert expected_action_for("in_progress") == "complete"
    assert expected_action_for("review") == "review"
    assert expected_action_for("done") == "none"


def test_next_status_transitions():
    assert next_status("todo", "claim") == "in_progress"
    assert next_status("in_progress", "complete") == "review"
    assert next_status("review", "review", "approve") == "done"
    assert next_status("review", "review", "request_changes") == "in_progress"
    assert next_status("todo", "complete") is None  # pulou claim


def test_terminal_completion_transition():
    assert is_terminal_completion("review", "review", "approve") is True
    assert is_terminal_completion("in_progress", "complete") is False
    assert is_terminal_completion("review", "review", "request_changes") is False


def test_classify_transition_reject_codes():
    assert classify_transition("done", "claim") == (False, REJECT_IMMUTABLE_DONE)
    assert classify_transition("done", "complete") == (False, REJECT_IMMUTABLE_DONE)
    assert classify_transition("todo", "complete") == (False, REJECT_MISSING_CLAIM)
    assert classify_transition("in_progress", "claim") == (False, REJECT_LOCK)
    # issue.report sempre admitido
    assert classify_transition("done", "issue.report") == (True, None)
    assert classify_transition("in_progress", "issue.report") == (True, None)


# --- RF04: slice_schema -----------------------------------------------------

def test_slice_schema_for_claim_omits_complete_and_file_updates():
    schema = _load_schema()
    sliced = slice_schema(schema, {"claim", "issue.report"})
    ev = sliced["properties"]["activity_event"]
    assert set(ev["properties"]["action"]["enum"]) == {"claim", "issue.report"}
    assert "verification" not in ev["properties"]
    assert "decision" not in ev["properties"]
    assert "file_updates" not in sliced["properties"]
    # allOf so com os branches relevantes
    consts = {b["if"]["properties"]["action"]["const"] for b in ev["allOf"]}
    assert consts == {"claim", "issue.report"}


def test_slice_schema_for_complete_keeps_file_updates():
    schema = _load_schema()
    sliced = slice_schema(schema, {"complete", "issue.report"})
    assert "file_updates" in sliced["properties"]
    ev = sliced["properties"]["activity_event"]
    assert "verification" in ev["properties"]
    assert "claim" not in ev["properties"]["action"]["enum"]


# --- RF05: dep_interfaces ---------------------------------------------------

def test_dep_interfaces_returns_only_done_deps():
    roadmap = {"tasks": [
        {"task_id": "A", "task_kind": "spec", "title": "Spec A", "status": "done",
         "outputs": {"files": ["docs/spec/A.md"]}},
        {"task_id": "B", "task_kind": "impl", "title": "Impl B", "status": "todo",
         "outputs": {"files": ["src/B.py"]}},
    ]}
    task = {"task_id": "C", "depends_on": ["A", "B"]}
    deps = dep_interfaces(roadmap, task)
    assert [d["task_id"] for d in deps] == ["A"]  # B nao esta done
    assert deps[0]["outputs"]["files"] == ["docs/spec/A.md"]


# --- RF06: filter_lessons / filter_issues -----------------------------------

def test_filter_lessons_respects_task_kind_and_applies_to():
    lessons = [
        {"lesson_id": "LES-1", "status": "active",
         "scope": {"task_kinds": ["impl"]},
         "enforcement": {"mode": "reject", "applies_to": "output_contract"},
         "rule": "regra X"},
        {"lesson_id": "LES-2", "status": "active",
         "scope": {"task_kinds": ["qa"]},
         "enforcement": {"mode": "reject", "applies_to": "workflow_gate"},
         "rule": "regra Y"},
    ]
    out = filter_lessons(lessons, task_kind="impl", expected_action="complete")
    assert [l["lesson_id"] for l in out] == ["LES-1"]


def test_filter_issues_only_open_and_linked():
    issues = [
        {"issue_id": "ISS-1", "status": "open", "baseline_id": "B-1", "title": "x"},
        {"issue_id": "ISS-2", "status": "resolved", "baseline_id": "B-1", "title": "y"},
    ]
    task = {"task_id": "T-1", "baseline_id": "B-1"}
    out = filter_issues(issues, task)
    assert [i["issue_id"] for i in out] == ["ISS-1"]


# --- Integracao: build_minimal_context muda com o estado --------------------

def test_minimal_context_changes_with_state():
    schema = _load_schema()
    contract = _load_contract()
    roadmap = {"meta": {"master_correlation_id": None}, "tasks": []}

    todo_task = {"task_id": "T-1", "task_kind": "impl", "status": "todo",
                 "depends_on": [], "title": "X", "description": "Y",
                 "targets": [], "outputs": {"files": ["src/X.py"]}}
    ctx_todo = build_minimal_context(roadmap, todo_task, contract, schema, lessons=[], issues=[])
    assert ctx_todo["expected_action"] == "claim"
    assert "boundaries" not in ctx_todo  # sem boundaries em claim
    assert "dep_interfaces" not in ctx_todo

    inprog_task = dict(todo_task, status="in_progress")
    ctx_inprog = build_minimal_context(roadmap, inprog_task, contract, schema, lessons=[], issues=[])
    assert ctx_inprog["expected_action"] == "complete"
    assert "boundaries" in ctx_inprog
    assert ctx_inprog["boundaries"]["write"] == ["src/**", "tests/**"]
    assert "dep_interfaces" in ctx_inprog
