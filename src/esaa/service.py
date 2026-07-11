from __future__ import annotations

from .events import (
    build_hotfix_event,
    build_issue_resolve_event,
    dumps_pretty,
    make_event,
    validate_hotfix_request,
)
from .execution import ExecutionMixin
from .project_profile_service import ProjectProfileMixin
from .seeds import (
    BASELINE_LESSONS,
    all_tasks_done,
    build_dispatch_context,
    find_planned_plugin_task,
    list_eligible_tasks,
    load_audit_seed,
    load_plugin_seeds,
    parallel_groups,
    seed_tasks,
    select_next_task,
    select_task_wave,
    tasks_with_planned_plugins,
)
from .service_core import ESAAServiceCore
from .submission import SubmissionMixin
from .task_admin import TaskAdminMixin


class ESAAService(TaskAdminMixin, SubmissionMixin, ExecutionMixin, ProjectProfileMixin, ESAAServiceCore):
    pass


__all__ = [
    "ESAAService",
    "make_event",
    "dumps_pretty",
    "validate_hotfix_request",
    "build_hotfix_event",
    "build_issue_resolve_event",
    "BASELINE_LESSONS",
    "seed_tasks",
    "load_plugin_seeds",
    "find_planned_plugin_task",
    "tasks_with_planned_plugins",
    "load_audit_seed",
    "all_tasks_done",
    "select_next_task",
    "select_task_wave",
    "list_eligible_tasks",
    "parallel_groups",
    "build_dispatch_context",
]
