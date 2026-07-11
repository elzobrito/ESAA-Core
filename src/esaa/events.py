from __future__ import annotations

import json
from typing import Any

from .boundary_paths import validate_hotfix_scope_entries
from .constants import SCHEMA_VERSION
from .errors import ESAAError
from .projector import materialize
from .provenance import resolve_runner
from .store import next_event_seq
from .utils import utc_now_iso


def make_event(event_seq: int, actor: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EV-{event_seq:08d}",
        "event_seq": event_seq,
        "ts": utc_now_iso(),
        "actor": actor,
        "runner": resolve_runner(),  # G08/PROV-01: proveniencia carimbada pelo single writer
        "action": action,
        "payload": payload,
    }


def validate_hotfix_request(
    current_events: list[dict[str, Any]],
    issue_payload: dict[str, Any],
) -> tuple[bool, str | None, str | None]:
    """FIX-1811 - Valida payload de issue.report para criar hotfix.



    Returns (ok, error_code, message). Se ok=True, hotfix pode ser criado.

    Se ok=False, hotfix NAO deve ser criado e error_code descreve a falha.

    """

    issue_id = issue_payload.get("issue_id")

    fixes = issue_payload.get("fixes")

    if not issue_id:

        return False, "HOTFIX_ISSUE_NOT_FOUND", "issue_id ausente"

    if not fixes:

        return False, "HOTFIX_TARGET_NOT_FOUND", "fixes ausente"

    # Materializa projecao atual para inspecionar issues e tasks

    roadmap, issues_view, _ = materialize(current_events)

    tasks_by_id = {t["task_id"]: t for t in roadmap.get("tasks", [])}

    issues_by_id = {i["issue_id"]: i for i in issues_view.get("issues", [])}

    # 1. fixes deve apontar para task existente

    target = tasks_by_id.get(fixes)

    if target is None:

        return False, "HOTFIX_TARGET_NOT_FOUND", f"fixes target {fixes} nao encontrado"

    # 2. Para imutavel-done, target deve estar done

    immutable = target.get("immutability", {}).get("done_is_immutable", False)

    if immutable and target.get("status") != "done":

        return (
            False,
            "HOTFIX_TARGET_NOT_DONE",
            (f"target {fixes} status={target.get('status')} (imutavel-done exige done)"),
        )

    # 3. scope_patch, quando declarado por comando administrativo, nao pode ser vazio.
    # Agent issue.report nao permite scope_patch no schema; nesse caminho o hotfix.create
    # usa o escopo padrao em build_hotfix_event.

    if "scope_patch" in issue_payload:

        scope = issue_payload.get("scope_patch") or []

        if not scope or not isinstance(scope, list):

            return False, "HOTFIX_SCOPE_INVALID", "scope_patch ausente ou vazio"
        try:
            validate_hotfix_scope_entries(scope)
        except ESAAError as exc:
            return False, exc.code or "HOTFIX_SCOPE_INVALID", exc.message

    # 4. issue deve existir e estar open

    if issue_id not in issues_by_id:

        return False, "HOTFIX_ISSUE_NOT_FOUND", f"issue {issue_id} nao encontrada"

    issue_status = issues_by_id[issue_id].get("status")

    if issue_status != "open":

        return False, "HOTFIX_ISSUE_NOT_OPEN", f"issue {issue_id} status={issue_status}"

    return True, None, None


def build_hotfix_event(
    current_events: list[dict[str, Any]],
    issue_payload: dict[str, Any],
    *,
    raise_on_invalid: bool = True,
) -> dict[str, Any] | None:
    """M-03 - Constroi hotfix.create event apos validar o request.

    Quando issue_id ou fixes ausentes, devolve None (issue.report comum, sem hotfix).
    Quando validate_hotfix_request falha:
      - raise_on_invalid=True (default): levanta ESAAError(code, message).
      - raise_on_invalid=False: devolve None (compat com callers que tratam None).
    Duplicate hotfix continua retornando None (graceful skip).
    """
    issue_id = issue_payload.get("issue_id")
    fixes = issue_payload.get("fixes")
    if not issue_id or not fixes:
        return None

    # M-03: validacao agora interna; caller nao precisa duplicar.
    ok, code, message = validate_hotfix_request(current_events, issue_payload)
    if not ok:
        if raise_on_invalid:
            raise ESAAError(code or "HOTFIX_INVALID", message or "invalid hotfix request")
        return None

    hotfix_task_id = f"HF-{issue_id}"
    for event in current_events:
        if event["action"] == "hotfix.create" and event["payload"].get("task_id") == hotfix_task_id:
            return None

    seq = next_event_seq(current_events)

    return make_event(
        seq,
        actor="orchestrator",
        action="hotfix.create",
        payload={
            "task_id": hotfix_task_id,
            "task_kind": "impl",
            "title": f"Hotfix for {issue_id}",
            "description": f"Apply a minimal hotfix to resolve issue {issue_id} without regressing immutable done tasks.",
            "depends_on": [],
            "targets": [issue_id],
            "outputs": {"files": [f"src/hotfix/{hotfix_task_id}.txt"]},
            "is_hotfix": True,
            "issue_id": issue_id,
            "fixes": fixes,
            "scope_patch": validate_hotfix_scope_entries(
                issue_payload.get("scope_patch", ["src/hotfix/"])
            ),
            "required_verification": issue_payload.get("required_verification", ["unit", "regression"]),
            "baseline_id": issue_payload.get("affected", {}).get("baseline_id", "B-000"),
        },
    )


def build_issue_resolve_event(
    current_events: list[dict[str, Any]],
    task: dict[str, Any],
    review_payload: dict[str, Any],
) -> dict[str, Any] | None:

    if not task.get("is_hotfix"):

        return None

    if review_payload.get("decision") != "approve":

        return None

    issue_id = task.get("issue_id")

    if not issue_id:

        return None

    for event in current_events:

        if event["action"] == "issue.resolve" and event["payload"].get("issue_id") == issue_id:

            return None

    seq = next_event_seq(current_events)

    return make_event(
        seq,
        actor="orchestrator",
        action="issue.resolve",
        payload={
            "issue_id": issue_id,
            "resolution": {
                "status": "resolved_by_hotfix",
                "hotfix_task_id": task["task_id"],
                "review_task_id": review_payload["task_id"],
                "checks": task.get("verification", {}).get("checks", []),
            },
        },
    )


def dumps_pretty(payload: dict[str, Any]) -> str:

    return json.dumps(payload, ensure_ascii=False, indent=2)
