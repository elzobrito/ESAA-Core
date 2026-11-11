"""Build administrative transitions against the prefix held by the store lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ESAAError
from .events import make_event
from .identity_history import validate_identity_history
from .projector import apply_events, projection_summary, replay_state, state_tasks
from .seeds import all_tasks_done
from .store import next_event_seq, parse_event_store


def prepare_orchestrator_events(
    events: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assign sequences and compute verification from this exact store prefix."""
    state = replay_state(events)
    known_ids = {task["task_id"] for task in state_tasks(state)}
    pending: list[dict[str, Any]] = []
    first_seq = next_event_seq(events)
    for candidate in candidates:
        event = {**candidate, "event_seq": first_seq + len(pending),
                 "event_id": f"EV-{first_seq + len(pending):08d}"}
        if event["action"] in {"task.create", "hotfix.create"}:
            task_id = event["payload"]["task_id"]
            if task_id in known_ids:
                raise ESAAError("DUPLICATE_TASK", f"task already exists: {task_id}")
            known_ids.add(task_id)
        apply_events(state, [event])
        pending.append(event)
    if all_tasks_done(state_tasks(state)) and projection_summary(state)["status"] != "success":
        event = make_event(first_seq + len(pending), "orchestrator", "run.end", {"status": "success"})
        apply_events(state, [event])
        pending.append(event)
    event = make_event(first_seq + len(pending), "orchestrator", "verify.start", {"strict": True})
    apply_events(state, [event])
    pending.append(event)
    event = make_event(first_seq + len(pending), "orchestrator", "verify.ok", {
        "projection_hash_sha256": projection_summary(state)["projection_hash_sha256"],
    })
    pending.append(event)
    return pending


def commit_orchestrator_events(
    root: Path, candidates: list[dict[str, Any]], append_transactionally: Any,
    *, dry_run: bool = False, precommit: Any = None, postcommit: Any = None,
    lock_max_age: float = 120.0,
) -> dict[str, Any]:
    if not candidates:
        raise ESAAError("INVALID_ARGUMENT", "at least one orchestrator event is required")
    pending: list[dict[str, Any]] = []

    def build(current: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if precommit is not None:
            precommit(current)
        pending[:] = prepare_orchestrator_events(current, candidates)
        return pending

    if dry_run:
        events = parse_event_store(root)
        pending = prepare_orchestrator_events(events, candidates)
        validate_identity_history(root, events + pending)
        final_run = projection_summary(replay_state(events + pending))
        committed = {key: final_run[key] for key in ("last_event_seq", "projection_hash_sha256")}
        committed["events_appended"] = len(pending)
    else:
        # No stale precondition: all decisions and sequences are built under this lock.
        committed = append_transactionally(root, build, lock_max_age=lock_max_age, after_append=postcommit)
    first = pending[0]
    result = {
        "status": "dry_run" if dry_run else "accepted", "actor": first["actor"],
        "action": first["action"], "event_id": first["event_id"],
        **committed, "verify_status": "ok",
    }
    if dry_run:
        result.update(would_append_events=len(pending), simulated_last_event_seq=result["last_event_seq"],
                      simulated_projection_hash_sha256=result["projection_hash_sha256"])
    for key in ("task_id", "issue_id", "error_code", "source_action"):
        if key in first["payload"]:
            result[key] = first["payload"][key]
    return result


def refresh_verification_hashes(
    events: list[dict[str, Any]], pending: list[dict[str, Any]],
) -> None:
    """Rebind verification records when a stale submission is retried on a new prefix."""
    state = replay_state(events)
    for event in pending:
        if event["action"] == "verify.ok":
            event["payload"] = {**event["payload"],
                                "projection_hash_sha256": projection_summary(state)["projection_hash_sha256"]}
        apply_events(state, [event])
