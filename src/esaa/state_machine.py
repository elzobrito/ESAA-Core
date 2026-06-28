"""Maquina de estado canonica do ESAA - autoridade local (RF01).

Centraliza as transicoes e os reject_codes do contrato. Outros modulos
(projector, validator, dispatch, service) consultam este modulo em vez
de re-derivar regras.

Diagrama:
    [todo] --claim--> [in_progress] --complete--> [review]
    [review] --review(approve)--> [done] (immutable)
    [review] --review(request_changes)--> [in_progress]
"""

from __future__ import annotations

from typing import Optional

# Estados de tarefa (TASK_STATUS em constants.py).
TASK_STATUSES = ("todo", "in_progress", "review", "done")

# Acoes do agente que afetam a maquina de estado.
AGENT_ACTIONS = ("claim", "complete", "review", "issue.report")

# Acao esperada por status (alinhado a AGENT_CONTRACT.dispatch_model.invocation_by_status).
EXPECTED_ACTION_BY_STATUS = {
    "todo": "claim",
    "in_progress": "complete",
    "review": "review",
    "done": "none",  # done e terminal; apenas issue.report e permitido
}

# Acoes permitidas por status (a esperada + issue.report como excecao).
ALLOWED_ACTIONS_BY_STATUS = {
    "todo": ("claim", "issue.report"),
    "in_progress": ("complete", "issue.report"),
    "review": ("review", "issue.report"),
    "done": ("issue.report",),
}

# Reject codes canonicos (alinhados a ORCHESTRATOR_CONTRACT.workflow_gates).
# Re-exportados do modulo canonico reject_codes (M-04) com aliases REJECT_* para
# backward-compat dos importadores existentes (projector, validator, etc.).
from .reject_codes import (
    ACTION_COLLAPSE as REJECT_ACTION_COLLAPSE,
    IMMUTABLE_DONE_VIOLATION as REJECT_IMMUTABLE_DONE,
    LOCK_VIOLATION as REJECT_LOCK,
    MISSING_CLAIM as REJECT_MISSING_CLAIM,
    MISSING_COMPLETE as REJECT_MISSING_COMPLETE,
    MISSING_VERIFICATION as REJECT_MISSING_VERIFICATION,
    PRIOR_STATUS_MISMATCH as REJECT_PRIOR_MISMATCH,
    WORKFLOW_GATE_VIOLATION as REJECT_WORKFLOW_GATE,
)


def expected_action_for(status: str) -> str:
    return EXPECTED_ACTION_BY_STATUS.get(status, "none")


def allowed_actions_for(status: str) -> tuple[str, ...]:
    return ALLOWED_ACTIONS_BY_STATUS.get(status, ("issue.report",))


def next_status(current: str, action: str, decision: Optional[str] = None) -> Optional[str]:
    """Devolve o proximo status para uma transicao valida, ou None se invalida."""
    if action == "claim" and current == "todo":
        return "in_progress"
    if action == "complete" and current == "in_progress":
        return "review"
    if action == "review" and current == "review":
        if decision == "approve":
            return "done"
        if decision == "request_changes":
            return "in_progress"
    return None


def classify_transition(current: str, action: str) -> tuple[bool, Optional[str]]:
    """Valida uma transicao e devolve (ok, reject_code).

    Mapeia cada combinacao invalida ao reject_code do contrato - em vez de
    cair sempre em INVALID_TRANSITION generico.
    """
    if action == "issue.report":
        return True, None  # issue.report permitido em qualquer estado

    if current == "done":
        return False, REJECT_IMMUTABLE_DONE

    if action == "claim":
        if current == "todo":
            return True, None
        # in_progress/review com claim -> ja em uso
        return False, REJECT_LOCK

    if action == "complete":
        if current == "in_progress":
            return True, None
        if current == "todo":
            return False, REJECT_MISSING_CLAIM  # pulou claim
        # current == review -> ja em revisao
        return False, REJECT_WORKFLOW_GATE

    if action == "review":
        if current == "review":
            return True, None
        return False, REJECT_WORKFLOW_GATE

    return False, REJECT_WORKFLOW_GATE
