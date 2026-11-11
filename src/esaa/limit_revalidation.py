from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ESAAError
from .projector import materialize
from .validator import validate_file_update_resource_limits


def _revalidate_limits_under_lock(
    root: Path,
    current_events: list[dict[str, Any]],
    checks: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    policy: dict[str, Any],
) -> None:
    if not checks:  # AUD-O1-010: sem file_updates nao ha o que revalidar; evita um replay sob lock
        return
    current_tasks = {t["task_id"]: t for t in materialize(current_events)[0]["tasks"]}
    for captured_task, updates in checks:
        current = current_tasks.get(captured_task["task_id"])
        if current is not None and current.get("resource_limits") != captured_task.get("resource_limits"):
            raise ESAAError("RESOURCE_LIMIT_INVALID", "task limits changed during submission")
        validate_file_update_resource_limits(updates, policy, current or captured_task)
