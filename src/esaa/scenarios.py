from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .projector import materialize
from .service import ESAAService
from .store import parse_event_store

HOTFIX_FLOW = [
    "issue.report",
    "hotfix.create",
    "claim",
    "complete",
    "orchestrator.file.write",
    "review",
    "issue.resolve",
    "verify.start",
    "verify.ok",
]


def _prepare_temp_workspace(source_root: Path) -> Path:
    target = Path(tempfile.mkdtemp(prefix="esaa-hotfix-trace-"))
    roadmap = target / ".roadmap"
    roadmap.mkdir(parents=True, exist_ok=True)
    for name in ("AGENT_CONTRACT.yaml", "agent_result.schema.json"):
        shutil.copy2(source_root / ".roadmap" / name, roadmap / name)
    return target


def _first_task_id(events: list[dict[str, Any]]) -> str:
    roadmap, _, _ = materialize(events)
    done = [task["task_id"] for task in roadmap["tasks"] if task.get("status") == "done"]
    if done:
        return sorted(done)[0]
    if roadmap["tasks"]:
        return sorted(task["task_id"] for task in roadmap["tasks"])[0]
    return "T-1000"


def _actor_for_task(task: dict[str, Any]) -> str:
    return {
        "spec": "agent-spec",
        "impl": "agent-impl",
        "qa": "agent-qa",
    }.get(task.get("task_kind"), "agent-spec")


def _default_output_path(task: dict[str, Any]) -> str:
    files = (task.get("outputs") or {}).get("files") or []
    if files:
        return files[0]
    kind = task.get("task_kind")
    task_id = task["task_id"]
    if kind == "impl":
        return f"src/{task_id}.txt"
    if kind == "qa":
        return f"docs/qa/{task_id}.md"
    return f"docs/{task_id}.md"


def _approve_review(service: ESAAService, task_id: str, owner: str) -> None:
    try:
        service.review_task(task_id, actor="agent-qa", decision="approve")
    except ESAAError as exc:
        if exc.code not in {"REVIEW_ROLE_VIOLATION", "LOCK_VIOLATION"}:
            raise
        service.review_task(task_id, actor=owner, decision="approve")


def _ensure_done_task(service: ESAAService, task_id: str) -> str:
    task = service.task_state(task_id)["task"]
    if task["status"] == "done":
        return task_id

    actor = _actor_for_task(task)
    if task["status"] == "todo":
        service.claim_task(task_id, actor=actor)
        task = service.task_state(task_id)["task"]
    if task["status"] == "in_progress":
        service.complete_task(
            task_id,
            actor=actor,
            checks=["baseline"],
            file_updates=[
                {
                    "path": _default_output_path(task),
                    "content": f"# {task_id}\n\nPrepared as immutable baseline for hotfix trace.\n",
                }
            ],
        )
        task = service.task_state(task_id)["task"]
    if task["status"] == "review":
        _approve_review(service, task_id, actor)
    return task_id


def _ordered_flow(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    index = 0
    for event in events:
        if index < len(HOTFIX_FLOW) and event["action"] == HOTFIX_FLOW[index]:
            found.append(event["action"])
            index += 1
    return found


def run_hotfix_trace(
    source_root: Path,
    target_root: Path | None = None,
    issue_id: str = "ISS-HOTFIX-TRACE",
) -> dict[str, Any]:
    workspace = target_root or _prepare_temp_workspace(source_root)
    service = ESAAService(workspace)

    if not parse_event_store(workspace):
        service.init(force=True, with_demo_tasks=True)

    events_before = parse_event_store(workspace)
    fixes = _ensure_done_task(service, _first_task_id(events_before))
    start_seq = service.verify()["last_event_seq"]

    issue = service.report_issue(
        fixes,
        actor="agent-qa",
        issue_id=issue_id,
        severity="medium",
        title="Demonstrable production hotfix trace",
        symptom="hotfix path must be visible as an event trail",
        repro_steps=["run esaa scenario hotfix"],
        fixes=fixes,
    )
    hotfix_task_id = f"HF-{issue_id}"
    service.claim_task(hotfix_task_id, actor="agent-hotfix")
    service.complete_task(
        hotfix_task_id,
        actor="agent-hotfix",
        checks=["unit", "regression"],
        notes="Apply deterministic hotfix trace artifact.",
        file_updates=[
            {
                "path": f"src/hotfix/{hotfix_task_id}.txt",
                "content": f"hotfix={issue_id}\nfixes={fixes}\n",
            }
        ],
        issue_id=issue_id,
        fixes=fixes,
    )
    _approve_review(service, hotfix_task_id, "agent-hotfix")
    verify = service.verify()

    events = parse_event_store(workspace)
    _, issues, _ = materialize(events)
    return {
        "workspace": str(workspace),
        "start_event_seq": start_seq,
        "final_event_seq": verify["last_event_seq"],
        "issue_id": issue_id,
        "hotfix_task_id": hotfix_task_id,
        "reported_event_id": issue.get("event_id"),
        "events_found": _ordered_flow(events),
        "verify_status": verify["verify_status"],
        "projection_hash_sha256": verify["projection_hash_sha256"],
        "files_touched": [f"src/hotfix/{hotfix_task_id}.txt"],
        "issues": issues["issues"],
    }
