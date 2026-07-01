from __future__ import annotations

from typing import Any

from .errors import ESAAError
from .validator import validate_boundary_grant, validate_g07_task_create_payload


def build_task_create_payload(
    *,
    task_id: str,
    task_kind: str,
    title: str,
    description: str | None = None,
    outputs: list[str] | None = None,
    depends_on: list[str] | None = None,
    targets: list[str] | None = None,
    boundary_grant: list[str] | None = None,
    task_type: str | None = None,
    acceptance_criteria: list[str] | None = None,
    required_review_mode: str | None = None,
    supersedes: list[str] | None = None,
    existing_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    task_id = task_id.strip()
    title = title.strip()
    description = description.strip() if description is not None else None
    outputs = [item.strip() for item in (outputs or [])]
    depends_on = [item.strip() for item in (depends_on or [])]
    targets = [item.strip() for item in (targets or [])]
    boundary_grant = validate_boundary_grant(boundary_grant) if boundary_grant else None
    task_type = task_type.strip() if task_type else None
    acceptance_criteria = [item.strip() for item in (acceptance_criteria or [])]
    required_review_mode = required_review_mode.strip() if required_review_mode else None
    supersedes = [item.strip() for item in (supersedes or [])]

    if task_kind not in {"spec", "impl", "qa"}:
        raise ESAAError("SCHEMA_INVALID", f"invalid task_kind: {task_kind}")
    if not task_id:
        raise ESAAError("SCHEMA_INVALID", "task_id is required")
    if not title:
        raise ESAAError("SCHEMA_INVALID", "title is required")

    payload = {
        "task_id": task_id,
        "task_kind": task_kind,
        "title": title,
        "description": description or title,
        "depends_on": depends_on,
        "targets": targets,
        "outputs": {"files": outputs},
    }
    if boundary_grant:
        payload["boundary_grant"] = boundary_grant
    if task_type:
        payload["task_type"] = task_type
    if acceptance_criteria:
        payload["acceptance_criteria"] = acceptance_criteria
    if required_review_mode:
        payload["required_review_mode"] = required_review_mode
    if supersedes:
        payload["supersedes"] = supersedes

    validate_g07_task_create_payload(payload, existing_task_ids or set())
    return payload
