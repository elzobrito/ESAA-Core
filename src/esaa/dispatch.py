"""Construcao de contexto minimo guiado pela maquina de estado.

Implementa RF04 (injecao dinamica de schema), RF05 (purificacao de
dependencias) e RF06 (filtragem de lessons/issues por task_kind).

A acao esperada e derivada do task_status (state_machine.expected_action_for),
e tudo que o agente recebe e fatiado por essa decisao local — economizando
tokens e reduzindo area de erro estrutural.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .project_profile import project_profile_summary
from .state_machine import allowed_actions_for, expected_action_for

# Quais campos de activity_event sao necessarios por acao.
_FIELDS_BY_ACTION = {
    "claim": {"action", "task_id", "prior_status"},
    "complete": {"action", "task_id", "prior_status", "notes", "verification"},
    "review": {"action", "task_id", "prior_status", "decision", "tasks", "review_mode"},
    "issue.report": {
        "action",
        "task_id",
        "prior_status",
        "issue_id",
        "severity",
        "title",
        "evidence",
        "category",
        "subtype",
        "affected",
        "fixes",
        "lesson",
    },
}

# Quais applies_to de lesson sao relevantes por acao.
_LESSON_RELEVANCE = {
    "claim": {"workflow_gate"},
    "complete": {"workflow_gate", "output_contract", "boundaries", "verification_gate"},
    "review": {"workflow_gate", "output_contract"},
    "issue.report": {"workflow_gate", "output_contract", "boundaries", "verification_gate", "template"},
    "none": set(),
}


def slice_schema(schema: dict[str, Any], allowed: Iterable[str]) -> dict[str, Any]:
    """Devolve um agent_result.schema reduzido aos branches/acoes permitidos."""
    allowed_set = set(allowed)
    sliced = deepcopy(schema)
    ev = sliced["properties"]["activity_event"]

    # 1) action enum restrito
    ev["properties"]["action"]["enum"] = sorted(allowed_set)

    # 2) properties: manter apenas a uniao dos campos das acoes permitidas
    needed: set[str] = set()
    for a in allowed_set:
        needed |= _FIELDS_BY_ACTION.get(a, set())
    ev["properties"] = {k: v for k, v in ev["properties"].items() if k in needed}

    # 3) allOf condicional: manter apenas branches cujo action.const esta permitido
    ev["allOf"] = [
        branch
        for branch in ev.get("allOf", [])
        if branch.get("if", {}).get("properties", {}).get("action", {}).get("const") in allowed_set
    ]

    # 4) file_updates so faz sentido com complete
    if "complete" not in allowed_set:
        sliced["properties"].pop("file_updates", None)
        sliced["allOf"] = []

    return sliced


def dep_interfaces(roadmap: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    """Interfaces (id, title, outputs) das dependencias 'done' — sem corpo (RF05)."""
    by_id = {t["task_id"]: t for t in roadmap.get("tasks", [])}
    out: list[dict[str, Any]] = []
    for dep_id in task.get("depends_on", []):
        dep = by_id.get(dep_id)
        if dep and dep.get("status") == "done":
            out.append(
                {
                    "task_id": dep["task_id"],
                    "task_kind": dep["task_kind"],
                    "title": dep["title"],
                    "outputs": dep.get("outputs", {"files": []}),
                }
            )
    return out


def _scope_dimension_matches(scope: dict[str, Any], name: str, values: set[str] | None) -> bool:
    expected = {str(item) for item in scope.get(name, [])}
    if not expected:
        return True
    return bool(values and expected.intersection(values))


def _scope_paths_match(scope: dict[str, Any], paths: set[str]) -> bool:
    patterns = [str(pattern).replace("\\", "/") for pattern in scope.get("paths", [])]
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path, pattern) for path in paths for pattern in patterns)


def _lesson_matches_scope(
    lesson: dict[str, Any],
    task: dict[str, Any],
    *,
    actor: str | None = None,
    runner: str | None = None,
) -> bool:
    scope = lesson.get("scope", {}) or {}
    task_paths = set(task.get("targets", []))
    task_paths.update(task.get("outputs", {}).get("files", []))
    review_modes = {task["required_review_mode"]} if task.get("required_review_mode") else set()
    return (
        _scope_dimension_matches(scope, "task_kinds", {task["task_kind"]})
        and _scope_dimension_matches(
            scope, "task_types", {task["task_type"]} if task.get("task_type") else set()
        )
        and _scope_dimension_matches(scope, "review_modes", review_modes)
        and _scope_paths_match(scope, task_paths)
        and _scope_dimension_matches(scope, "actors", {actor} if actor else set())
        and _scope_dimension_matches(scope, "runners", {runner} if runner else set())
    )


def filter_lessons(
    lessons: list[dict[str, Any]],
    task: dict[str, Any] | str | None = None,
    expected_action: str = "none",
    *,
    task_kind: str | None = None,
    actor: str | None = None,
    runner: str | None = None,
) -> list[dict[str, Any]]:
    """Lessons aplicaveis: OR dentro da dimensao, AND entre dimensoes (G07)."""
    if task is None:
        if task_kind is None:
            raise TypeError("filter_lessons requires task or task_kind")
        task_data = {"task_kind": task_kind}
    else:
        task_data = {"task_kind": task} if isinstance(task, str) else task
    relevance = _LESSON_RELEVANCE.get(expected_action, set())
    out = []
    for lesson in lessons:
        status = lesson.get("status")
        if status not in {"active", "experimental"}:
            continue
        if not _lesson_matches_scope(lesson, task_data, actor=actor, runner=runner):
            continue
        applies = lesson.get("enforcement", {}).get("applies_to")
        if applies and relevance and applies not in relevance:
            continue
        out.append(
            {
                "lesson_id": lesson["lesson_id"],
                "status": status,
                "rule": lesson.get("rule"),
                "enforcement": lesson.get("enforcement", {}),
            }
        )
    return out


def filter_issues(issues: list[dict[str, Any]], task: dict[str, Any]) -> list[dict[str, Any]]:
    """Issues abertos que afetam esta tarefa (baseline ou link explicito) (RF06)."""
    out = []
    task_baseline = task.get("baseline_id")
    task_id = task["task_id"]
    for issue in issues:
        if issue.get("status") != "open":
            continue
        baseline_match = task_baseline and issue.get("baseline_id") == task_baseline
        links = issue.get("links", {}) or {}
        link_match = task_id in {
            links.get("reported_by_task_id"),
            links.get("fixes_task_id"),
            links.get("hotfix_task_id"),
        }
        if baseline_match or link_match:
            out.append(
                {
                    "issue_id": issue["issue_id"],
                    "severity": issue.get("severity"),
                    "title": issue.get("title"),
                }
            )
    return out


def build_minimal_context(
    roadmap: dict[str, Any],
    task: dict[str, Any],
    contract: dict[str, Any],
    schema: dict[str, Any],
    lessons: list[dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
    project_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Contexto despachado ao agente — fatiado pela maquina de estado.

    Para 'todo' devolve so o slice de claim (sem verification/file_updates/deps).
    Para 'in_progress' acrescenta boundaries, dep_interfaces, lessons/issues filtradas.
    Para 'review' devolve o slice de review + a verification do complete.
    Para 'done' devolve so o slice de issue.report.
    """
    status = task["status"]
    expected = expected_action_for(status)
    allowed = allowed_actions_for(status)

    task_ctx: dict[str, Any] = {
        "task_id": task["task_id"],
        "task_kind": task["task_kind"],
        "status": status,
        "title": task.get("title"),
        "description": task.get("description"),
        "depends_on": task.get("depends_on", []),
        "targets": task.get("targets", []),
        "outputs": task.get("outputs", {"files": []}),
    }
    for optional in (
        "is_hotfix",
        "issue_id",
        "fixes",
        "scope_patch",
        "required_verification",
        "baseline_id",
        "boundary_grant",
        "task_type",
        "acceptance_criteria",
        "required_review_mode",
        "supersedes",
        "superseded_by",
    ):
        if optional in task:
            task_ctx[optional] = task[optional]

    ctx: dict[str, Any] = {
        "expected_action": expected,
        "allowed_actions": list(allowed),
        "schema_slice": slice_schema(schema, allowed),
    }

    # Apenas no complete o agente precisa de boundaries detalhadas, deps e lessons amplas.
    if expected == "complete":
        kind = task["task_kind"]
        boundaries = contract["boundaries"]["by_task_kind"].get(kind, {})
        ctx["boundaries"] = {
            "read": boundaries.get("read", []),
            "write": boundaries.get("write", []),
            "forbidden_write": boundaries.get("forbidden_write", []),
        }

    if lessons is not None:
        ctx["lessons"] = filter_lessons(lessons, task, expected)

    if expected == "complete":
        ctx["dep_interfaces"] = dep_interfaces(roadmap, task)

    ctx["task"] = task_ctx

    if issues is not None and expected == "complete":
        ctx["issues"] = filter_issues(issues, task)

    profile_summary = project_profile_summary(project_profile)
    if profile_summary is not None:
        ctx["project_profile"] = profile_summary

    # Em review o agente-qa precisa ver a verification produzida no complete.
    if expected == "review" and "verification" in task:
        ctx["completed_verification"] = task["verification"]

    ctx["correlation"] = {
        "master_correlation_id": roadmap["meta"].get("master_correlation_id"),
        "task_id": task["task_id"],
    }

    return ctx
