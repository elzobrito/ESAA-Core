"""Audit penalizing delivery failures, without disguising store or authority errors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import CorruptedStoreError, ESAAError
from .events import make_event
from .identity import authorize_agent_event, project_registry
from .limit_revalidation import _revalidate_limits_under_lock
from .orchestrator_commit import prepare_orchestrator_events
from .projector import replay_state, state_tasks
from .runtime_policy import is_blocked_by_max_attempts, load_policy
from .store import append_transactional

_NON_DELIVERY_PREFIXES = (
    "AUTH_", "ACTOR_", "TRUST_", "ANCHOR_", "PRINCIPAL_", "OWNER_", "IDENTITY_",
    "RUNNER_", "STORE_", "EVENT_", "STALE_STATE_",
)
_NON_DELIVERY_CODES = {
    "APPEND_VERIFY_FAILED", "JSONL_INVALID", "CHAIN_BROKEN", "BLOCKED_ENVIRONMENT",
    "ORCHESTRATOR_IMPERSONATION", "OPERATOR_REQUIRED", "REVIEW_ROLE_VIOLATION",
    "SELF_REVIEW_FORBIDDEN", "MAX_ATTEMPTS_EXCEEDED", "POLICY_INVALID",
    "PRIOR_STATUS_MISMATCH", "DEPENDENCY_NOT_DONE", "TASK_SUPERSEDED",
}


def record_submission_rejection(
    root: Path, error: Exception, activity: dict[str, Any], actor: str,
    base_events: list[dict[str, Any]], *, dry_run: bool, authorization: Any = None,
) -> None:
    if (dry_run or not isinstance(error, ESAAError) or isinstance(error, CorruptedStoreError)
        or not error.penalizes_counter or error.code in _NON_DELIVERY_CODES
        or error.code.startswith(_NON_DELIVERY_PREFIXES)):
        return
    task_id, action = activity.get("task_id"), activity.get("action")
    if not isinstance(task_id, str) or not isinstance(action, str):
        return

    def build(current: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # A post-append effect failure is not a rejected delivery. Do not append a
        # contradictory rejection when this operation (or a concurrent one) committed.
        if any(e["actor"] == actor and e["action"] == action
               and e["payload"].get("task_id") == task_id for e in current[len(base_events):]):
            return []
        policy = load_policy(root)
        task = next((task for task in state_tasks(replay_state(current)) if task["task_id"] == task_id), None)
        if task is None:
            return []
        principal = authorize_agent_event(
            root=root, events=current, actor=actor, task=task, action=action,
            decision=str(activity.get("decision") or ""), authorization=authorization, policy=policy,
        )
        # Some legacy operations (issue.report or an invalid action) have no signed
        # credential contract. With identity active they cannot charge another
        # principal's attempt budget merely by declaring its task id.
        if project_registry(current)["active"] and "_principal_id" not in principal:
            return []
        maximum = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)
        if is_blocked_by_max_attempts(current, task_id, maximum):
            raise ESAAError("MAX_ATTEMPTS_EXCEEDED", f"task {task_id} reached {maximum} penalizing rejections",
                            penalizes_counter=False)
        rejected = make_event(0, "orchestrator", "output.rejected", {
            "task_id": task_id, "error_code": error.code, "message": error.message,
            "source_action": action, "source_actor": actor,
            **({"source_principal_id": principal["_principal_id"]} if "_principal_id" in principal else {}),
        })
        return prepare_orchestrator_events(current, [rejected])

    append_transactional(root, build)


def revalidate_submission(
    root: Path, events: list[dict[str, Any]], task: dict[str, Any], updates: list[dict[str, Any]],
) -> None:
    """Enforce the latest attempt budget and resource limits at the commit boundary."""
    policy = load_policy(root)
    maximum = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)
    if is_blocked_by_max_attempts(events, task["task_id"], maximum):
        raise ESAAError("MAX_ATTEMPTS_EXCEEDED", f"task {task['task_id']} reached {maximum} penalizing rejections",
                        penalizes_counter=False)
    _revalidate_limits_under_lock(root, events, [(task, updates)] if updates else [], policy)
