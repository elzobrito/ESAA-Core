from __future__ import annotations

import hashlib
import importlib
import inspect
from pathlib import Path

from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store

SERVICE_MODULES = (
    "src/esaa/service.py",
    "src/esaa/service_core.py",
    "src/esaa/submission.py",
    "src/esaa/execution.py",
    "src/esaa/task_admin.py",
    "src/esaa/seeds.py",
    "src/esaa/events.py",
)


PUBLIC_SYMBOLS = {
    "make_event": "esaa.events",
    "dumps_pretty": "esaa.events",
    "validate_hotfix_request": "esaa.events",
    "build_hotfix_event": "esaa.events",
    "build_issue_resolve_event": "esaa.events",
    "BASELINE_LESSONS": "esaa.seeds",
    "seed_tasks": "esaa.seeds",
    "load_plugin_seeds": "esaa.seeds",
    "find_planned_plugin_task": "esaa.seeds",
    "tasks_with_planned_plugins": "esaa.seeds",
    "load_audit_seed": "esaa.seeds",
    "all_tasks_done": "esaa.seeds",
    "select_next_task": "esaa.seeds",
    "select_task_wave": "esaa.seeds",
    "list_eligible_tasks": "esaa.seeds",
    "parallel_groups": "esaa.seeds",
    "build_dispatch_context": "esaa.seeds",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_service_facade_reexports_public_symbols_from_new_modules() -> None:
    service = importlib.import_module("esaa.service")
    for symbol, module_name in PUBLIC_SYMBOLS.items():
        origin = importlib.import_module(module_name)
        assert getattr(service, symbol) is getattr(origin, symbol)

    from esaa.execution import ExecutionMixin
    from esaa.service_core import ESAAServiceCore
    from esaa.submission import SubmissionMixin
    from esaa.task_admin import TaskAdminMixin

    assert issubclass(service.ESAAService, (TaskAdminMixin, SubmissionMixin, ExecutionMixin, ESAAServiceCore))


def test_service_modules_stay_under_500_lines(repo_root: Path) -> None:
    for rel in SERVICE_MODULES:
        path = repo_root / rel
        assert path.exists(), f"missing {rel}"
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 500, rel


def test_decomposed_service_replay_golden_with_edit_update(contract_bundle: Path) -> None:
    target = contract_bundle / "docs/spec/T-1000.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    base = "# Spec\nstatus: draft\n"
    target.write_text(base, encoding="utf-8", newline="")

    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": "T-1000",
                "prior_status": "in_progress",
                "verification": {"checks": ["edit replay"]},
            },
            "file_updates": [
                {
                    "path": "docs/spec/T-1000.md",
                    "base_sha256": _sha(base),
                    "edits": [{"old_string": "status: draft", "new_string": "status: ready"}],
                }
            ],
        },
        actor="agent-spec",
    )

    events = parse_event_store(contract_bundle)
    first = materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]
    second = materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]

    assert first == second
    assert inspect.getmodule(ESAAService).__name__ == "esaa.service"
