"""Operator-only amendments of pending task metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .boundary_paths import validate_hotfix_scope_entries
from .errors import ESAAError
from .events import make_event
from .projector import materialize
from .runtime_policy import require_operator_runner
from .store import next_event_seq, parse_event_store, require_task
from .validator import validate_boundary_grant

if TYPE_CHECKING:
    from pathlib import Path


class TaskAmendMixin:
    if TYPE_CHECKING:
        root: Path

        def _commit_orchestrator_events(
            self,
            candidate_events: list[dict[str, Any]],
            dry_run: bool = False,
            precommit: Any = None,
            postcommit: Any = None,
        ) -> dict[str, Any]: ...

        def _validate_roadmap_projection_schema(self, roadmap: dict[str, Any]) -> None: ...
        def _policy(self) -> dict[str, Any]: ...

    def amend_task(
        self,
        task_id: str,
        description: str | None = None,
        title: str | None = None,
        acceptance_criteria: list[str] | None = None,
        task_kind: str | None = None,
        task_type: str | None = None,
        depends_on: list[str] | None = None,
        outputs: list[str] | None = None,
        required_review_mode: str | None = None,
        required_verification: list[str] | None = None,
        dry_run: bool = False,
        *,
        boundary_grant: list[str] | None = None,
        clear_boundary_grants: bool = False,
        scope_patch: list[str] | None = None,
        executable_checks: list[str] | None = None,
        resource_limits: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        require_operator_runner(self.root, "task amend")
        events = parse_event_store(self.root)
        roadmap, _, _ = materialize(events)
        task = require_task(roadmap, task_id)
        if task["status"] != "todo":
            raise ESAAError("INVALID_TRANSITION", f"task.amend only allowed for todo tasks: {task_id}")

        payload: dict[str, Any] = {"task_id": task_id}
        if description is not None:
            payload["description"] = description.strip()
        if title is not None:
            payload["title"] = title.strip()
        if acceptance_criteria is not None:
            payload["acceptance_criteria"] = [item.strip() for item in acceptance_criteria if item.strip()]
        if task_kind is not None:
            payload["task_kind"] = task_kind.strip()
        if task_type is not None:
            payload["task_type"] = task_type.strip()
        if depends_on is not None:
            payload["depends_on"] = [item.strip() for item in depends_on if item.strip()]
        if outputs is not None:
            payload["outputs"] = {"files": [item.strip() for item in outputs if item.strip()]}
        if required_review_mode is not None:
            payload["required_review_mode"] = required_review_mode.strip()
        if required_verification is not None:
            payload["required_verification"] = [
                item.strip() for item in required_verification if item.strip()
            ]
        if boundary_grant is not None and clear_boundary_grants:
            raise ESAAError("INVALID_ARGUMENT", "grant and clear-boundary-grants are mutually exclusive")
        if boundary_grant is not None or clear_boundary_grants:
            payload["boundary_grant"] = validate_boundary_grant(boundary_grant or [])
        if scope_patch is not None:
            if not task.get("is_hotfix"):
                raise ESAAError("INVALID_ARGUMENT", "scope_patch amendment requires a hotfix")
            payload["scope_patch"] = validate_hotfix_scope_entries(scope_patch)
        if executable_checks is not None:
            from .verification_config import validate_check_ids

            payload["executable_checks"] = validate_check_ids(executable_checks, events)
        if resource_limits is not None:
            from .task_resource_limits import resolve_task_limits
            from .validator import resource_limits_from_policy

            policy = self._policy()
            try:
                from .task_resource_limits import _validate

                payload["resource_limits"] = _validate(
                    resource_limits, name="resource_limits", require_all=False
                )
                resolve_task_limits(
                    resource_limits_from_policy(policy),
                    policy.get("resource_limit_caps"),
                    payload["resource_limits"],
                )
            except ValueError as exc:
                raise ESAAError("RESOURCE_LIMIT_INVALID", str(exc)) from exc
        if len(payload) == 1:
            raise ESAAError("INVALID_ARGUMENT", "task.amend requires at least one field to update")

        event = make_event(next_event_seq(events), actor="orchestrator", action="task.amend", payload=payload)
        preview_roadmap, _, _ = materialize(events + [event])
        self._validate_roadmap_projection_schema(preview_roadmap)
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result["schema_validated"] = ".roadmap/roadmap.schema.json"
        result["task_id"] = task_id
        return result
