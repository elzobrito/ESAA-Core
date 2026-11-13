"""Audited resource-limit changes for in-progress tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import ESAAError
from .events import make_event
from .file_effects import STAGING_DIR
from .projector import materialize
from .runtime_policy import require_operator_runner
from .store_runtime import next_event_seq, parse_event_store, require_task
from .task_resource_limits import _validate, resolve_task_limits
from .validator import resource_limits_from_policy

if TYPE_CHECKING:
    from pathlib import Path


class TaskLimitsAdminMixin:
    if TYPE_CHECKING:
        root: Path

        def _policy(self) -> dict[str, Any]: ...

        def _commit_orchestrator_events(
            self,
            candidate_events: list[dict[str, Any]],
            dry_run: bool = False,
            precommit: Any = None,
            postcommit: Any = None,
        ) -> dict[str, Any]: ...

        def _validate_roadmap_projection_schema(self, roadmap: dict[str, Any]) -> None: ...

    def set_task_limits(
        self,
        task_id: str,
        resource_limits: dict[str, int],
        *,
        reason: str,
        authorized_by: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        require_operator_runner(self.root, "task limits set")
        reason = (reason or "").strip()
        authorized_by = (authorized_by or "").strip()
        if not reason:
            raise ESAAError("INVALID_ARGUMENT", "task.limits.set requires a non-empty reason")
        if not authorized_by:
            raise ESAAError("INVALID_ARGUMENT", "task.limits.set requires authorized_by")
        try:
            requested = _validate(resource_limits, name="resource_limits", require_all=False)
        except ValueError as exc:
            raise ESAAError("RESOURCE_LIMIT_INVALID", str(exc)) from exc
        if not requested:
            raise ESAAError("INVALID_ARGUMENT", "task.limits.set requires at least one limit")

        events = parse_event_store(self.root)
        roadmap, _, _ = materialize(events)
        task = require_task(roadmap, task_id)
        if task["status"] == "done":
            raise ESAAError("IMMUTABLE_DONE_VIOLATION", f"cannot change limits of done task: {task_id}")
        if task["status"] != "in_progress":
            raise ESAAError(
                "INVALID_TRANSITION",
                f"task.limits.set is only allowed for in_progress tasks: {task_id}",
            )

        staging = self.root / STAGING_DIR
        if staging.exists() and any(staging.iterdir()):
            raise ESAAError("LIMITS_CHANGE_BLOCKED", "cannot change limits while a submission is staged")

        policy = self._policy()
        try:
            resolved = resolve_task_limits(
                resource_limits_from_policy(policy),
                policy.get("resource_limit_caps"),
                requested,
            )
        except ValueError as exc:
            raise ESAAError("RESOURCE_LIMIT_INVALID", str(exc)) from exc
        previous = dict(task["resource_limits"]) if "resource_limits" in task else None
        if previous == requested:
            raise ESAAError("INVALID_ARGUMENT", "resource_limits are unchanged")

        payload = {
            "task_id": task_id,
            "previous": previous,
            "resource_limits": requested,
            "resolved_resource_limits": resolved,
            "reason": reason,
            "authorized_by": authorized_by,
        }
        event = make_event(
            next_event_seq(events), actor="orchestrator", action="task.limits.set", payload=payload
        )
        preview_roadmap, _, _ = materialize(events + [event])
        try:
            self._validate_roadmap_projection_schema(preview_roadmap)
        except ESAAError as exc:
            if exc.code == "SCHEMA_INVALID":
                raise ESAAError(
                    "SCHEMA_INVALID",
                    "active roadmap schema rejects resource_limits; run esaa contract migrate first",
                ) from exc
            raise
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result["task_id"] = task_id
        result["resource_limits"] = requested
        result["previous"] = previous
        return result
