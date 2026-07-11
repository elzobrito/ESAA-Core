from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .events import make_event
from .projector import materialize
from .project_profile import (
    build_onboarding_tasks,
    normalize_project_profile,
    project_profile_view,
    validate_project_profile,
)
from .store import load_project_profile, next_event_seq, parse_event_store


class ProjectProfileMixin:
    def show_project_profile(self) -> dict[str, Any]:
        profile = load_project_profile(self.root)
        if profile is None:
            events = parse_event_store(self.root)
            profile = project_profile_view(events)
        return {"project_profile": profile}

    def onboard(self, answers: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        roadmap_dir = self.root / ".roadmap"
        if not roadmap_dir.is_dir():
            raise ESAAError("ROADMAP_DIR_MISSING", f".roadmap not found under {self.root}; run esaa bootstrap first")

        schema_path = roadmap_dir / "project_profile.schema.json"
        if not schema_path.exists():
            schema_path = Path(str(resources.files("esaa").joinpath("templates", "project_profile.schema.json")))

        events = parse_event_store(self.root)
        roadmap, _, _ = materialize(events)
        profile = normalize_project_profile(self.root, answers)
        profile_view = {
            "meta": {
                "schema_version": "0.4.1",
                "generated_by": "esaa.project_profile",
                "source_event_store": ".roadmap/activity.jsonl",
                "last_event_seq": next_event_seq(events),
                "updated_at": "1970-01-01T00:00:00Z",
            },
            **profile,
        }
        validate_project_profile(profile_view, schema_path)

        existing_ids = {task["task_id"] for task in roadmap.get("tasks", [])}
        todo_seed_ids = {
            task["task_id"]
            for task in roadmap.get("tasks", [])
            if task["task_id"] in {"T-1000", "T-1010", "T-1020"} and task.get("status") == "todo"
        }
        tasks = [
            task
            for task in build_onboarding_tasks(profile, todo_seed_ids)
            if task["task_id"] not in existing_ids
        ]

        seq = next_event_seq(events)
        candidate_events = [make_event(seq, actor="orchestrator", action="project.profile.set", payload=profile)]
        seq += 1
        for task in tasks:
            candidate_events.append(make_event(seq, actor="orchestrator", action="task.create", payload=task))
            seq += 1

        result = self._commit_orchestrator_events(candidate_events, dry_run=dry_run)
        result["project_profile"] = {
            "operator": profile["operator"],
            "project_name": profile["project_name"],
            "domain": profile["domain"],
            "language": profile["language"],
        }
        result["tasks_created"] = [task["task_id"] for task in tasks]
        result["guides_detected"] = profile["guide_topology"]["guides"]
        return result
