from __future__ import annotations

from typing import Any

from .base import AgentAdapter


class MockAgentAdapter(AgentAdapter):
    def __init__(self, agent_id: str = "agent-mock") -> None:
        self.agent_id = agent_id

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def execute(self, dispatch_context: dict[str, Any]) -> dict[str, Any]:
        task = dispatch_context["task"]
        task_id = task["task_id"]
        status = task["status"]

        if status == "todo":
            return {
                "activity_event": {
                    "action": "claim",
                    "task_id": task_id,
                    "prior_status": "todo",
                    "notes": "mock claim",
                }
            }

        if status == "in_progress":
            checks = [f"mock-check:{task_id}"]
            if task.get("is_hotfix"):
                checks.append(f"mock-hotfix-check:{task_id}")

            output_file = _choose_output_file(task)
            file_updates = []
            if output_file:
                file_updates = [
                    {
                        "path": output_file,
                        "content": _build_file_content(task),
                    }
                ]

            event = {
                "action": "complete",
                "task_id": task_id,
                "prior_status": "in_progress",
                "notes": "mock complete",
                "verification": {"checks": checks},
            }
            if task.get("is_hotfix"):
                event["issue_id"] = task["issue_id"]
                event["fixes"] = task["fixes"]
            return {"activity_event": event, "file_updates": file_updates}

        if status == "review":
            return {
                "activity_event": {
                    "action": "review",
                    "task_id": task_id,
                    "prior_status": "review",
                    "decision": "approve",
                    "tasks": [task_id],
                    "notes": "mock review approve",
                }
            }

        return {
            "activity_event": {
                "action": "issue.report",
                "task_id": task_id,
                "prior_status": status if status in {"todo", "in_progress", "review"} else "in_progress",
                "issue_id": f"ISS-MOCK-{task_id}",
                "severity": "low",
                "title": "Task not actionable",
                "evidence": {
                    "symptom": f"task status is {status}",
                    "repro_steps": [f"load task {task_id}", f"check status {status}"],
                },
            }
        }


def _choose_output_file(task: dict[str, Any]) -> str:
    outputs = task.get("outputs", {}).get("files", [])
    task_kind = task["task_kind"]
    for output in outputs:
        if output.startswith("runtime://"):
            continue
        if _path_allowed_for_kind(output, task_kind):
            return output
    if task_kind == "spec":
        return f"docs/spec/{task['task_id']}.md"
    if task_kind == "impl":
        return f"src/{task['task_id'].lower()}.txt"
    return f"docs/qa/{task['task_id']}.md"


def _path_allowed_for_kind(path: str, task_kind: str) -> bool:
    if task_kind == "spec":
        return path.startswith("docs/")
    if task_kind == "impl":
        return path.startswith(("src/", "tests/"))
    if task_kind == "qa":
        return path.startswith(("docs/qa/", "tests/"))
    return path.startswith("src/hotfix/")


def _build_file_content(task: dict[str, Any]) -> str:
    return (
        f"# {task['task_id']}\n\n"
        f"- kind: {task['task_kind']}\n"
        f"- generated_by: mock_adapter\n"
        f"- note: deterministic fixture output\n"
    )
