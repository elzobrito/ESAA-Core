"""Audited recovery of stalled tasks, committed against the locked prefix."""

from __future__ import annotations

from typing import Any

from .errors import ESAAError
from .events import make_event
from .projector import materialize
from .runtime_policy import require_operator_runner
from .store_runtime import next_event_seq, parse_event_store, require_task


def release_task(service: Any, task_id: str, *, reason: str, dry_run: bool = False) -> dict[str, Any]:
    require_operator_runner(service.root, "task release")
    if not isinstance(reason, str) or not reason.strip():
        raise ESAAError("INVALID_ARGUMENT", "task release requires a non-empty reason")
    events = parse_event_store(service.root)
    task = require_task(materialize(events)[0], task_id)
    previous = {key: task.get(key) for key in ("status", "assigned_to", "started_at")}

    def revision(history: list[dict[str, Any]]) -> int:
        return max(
            (e["event_seq"] for e in history if (e.get("payload") or {}).get("task_id") == task_id), default=0
        )

    expected_revision = revision(events)
    event = make_event(
        next_event_seq(events),
        actor="orchestrator",
        action="task.release",
        payload={
            "task_id": task_id,
            "reason": reason.strip(),
            "previous": previous,
            "expected_revision": expected_revision,
        },
    )
    # The projector checks the captured claim under the commit lock as well,
    # preventing a stale release from clearing a subsequent claimant.
    materialize(events + [event])

    def precommit(current: list[dict[str, Any]]) -> None:
        require_operator_runner(service.root, "task release")
        if revision(current) != expected_revision:
            raise ESAAError("PRIOR_STATUS_MISMATCH", "task changed since release was prepared")

    return service._commit_orchestrator_events([event], dry_run=dry_run, precommit=precommit)
