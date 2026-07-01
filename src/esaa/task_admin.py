from __future__ import annotations

from typing import Any

from .activity_admin import apply_activity_clear, plan_activity_clear
from .errors import ESAAError
from .events import build_hotfix_event, make_event
from .notifications import (
    completion_alarm_enabled_from_env,
    play_transition_message,
    transition_messages_enabled_from_env,
)
from .projector import materialize
from .runner_inputs import load_runtime_capabilities
from .seeds import (
    build_dispatch_context,
    find_planned_plugin_task,
    tasks_with_planned_plugins,
)
from .state_machine import allowed_actions_for, expected_action_for
from .store import (
    load_agent_contract,
    load_agent_result_schema,
    next_event_seq,
    parse_event_store,
    require_task,
)
from .task_creation import build_task_create_payload


class TaskAdminMixin:
    def create_task(
        self,
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
        dry_run: bool = False,
    ) -> dict[str, Any]:
        events = parse_event_store(self.root)
        roadmap, _, _ = materialize(events)
        tasks, _ = tasks_with_planned_plugins(self.root, roadmap["tasks"])

        if any(task["task_id"] == task_id for task in tasks):
            raise ESAAError("DUPLICATE_TASK", f"task already exists: {task_id}")

        payload = build_task_create_payload(
            task_id=task_id,
            task_kind=task_kind,
            title=title,
            description=description,
            outputs=outputs,
            depends_on=depends_on,
            targets=targets,
            boundary_grant=boundary_grant,
            task_type=task_type,
            acceptance_criteria=acceptance_criteria,
            required_review_mode=required_review_mode,
            supersedes=supersedes,
            existing_task_ids={task["task_id"] for task in tasks},
        )

        event = make_event(
            next_event_seq(events), actor="orchestrator", action="task.create", payload=payload
        )

        preview_roadmap, _, _ = materialize(events + [event])

        self._validate_roadmap_projection_schema(preview_roadmap)

        result = self._commit_orchestrator_events([event], dry_run=dry_run)

        result["schema_validated"] = ".roadmap/roadmap.schema.json"

        return result

    def clear_activity(
        self,
        force: bool = False,
        dry_run: bool = False,
        backup_dir: str = ".roadmap/backups",
    ) -> dict[str, Any]:
        result = plan_activity_clear(self.root, force=force, dry_run=dry_run, backup_dir=backup_dir)
        if dry_run:
            result.pop("_backup_path", None)
            result.pop("_raw", None)
            return result

        apply_activity_clear(self.root, result)
        verify = self.verify()
        result.update(
            {
                "last_event_seq": verify["last_event_seq"],
                "verify_status": verify["verify_status"],
                "projection_hash_sha256": verify["projection_hash_sha256"],
            }
        )

        return result

    def task_state(self, task_id: str) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, _, _ = materialize(events)

        tasks, sources = tasks_with_planned_plugins(self.root, roadmap["tasks"])

        task = require_task({**roadmap, "tasks": tasks}, task_id)

        status = task["status"]

        return {
            "task": task,
            "source": sources.get(task_id, "event_store"),
            "expected_action": expected_action_for(status),
            "allowed_actions": list(allowed_actions_for(status)),
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "verify_status": roadmap["meta"]["run"]["verify_status"],
            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
        }

    def dispatch_context(self, task_id: str) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, issues, lessons = materialize(events)

        tasks, sources = tasks_with_planned_plugins(self.root, roadmap["tasks"])

        roadmap = {**roadmap, "tasks": tasks}

        task = require_task(roadmap, task_id)

        contract = load_agent_contract(self.root)

        schema = load_agent_result_schema(self.root)

        context = build_dispatch_context(
            roadmap,
            task,
            contract,
            schema=schema,
            lessons=lessons.get("lessons", []),
            issues=issues.get("issues", []),
        )

        context["last_event_seq"] = roadmap["meta"]["run"]["last_event_seq"]

        context["source"] = sources.get(task_id, "event_store")

        runtime_capabilities = load_runtime_capabilities(self.root)
        if runtime_capabilities:
            context["runtime_capabilities"] = runtime_capabilities

        return context

    def claim_task(
        self,
        task_id: str,
        actor: str,
        notes: str | None = None,
        notify_transition: bool | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        admission = None if dry_run else self._admit_planned_task_if_needed(task_id)

        activity_event: dict[str, Any] = {
            "action": "claim",
            "task_id": task_id,
            "prior_status": "todo",
        }

        if notes:
            activity_event["notes"] = notes

        result = self._submit_command(
            {"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run
        )

        if admission:
            result["admission"] = {
                "action": "task.create",
                "task_id": task_id,
                "events_appended": admission["events_appended"],
            }

            result["events_appended_total"] = result["events_appended"] + admission["events_appended"]

        should_notify = notify_transition
        if should_notify is None:
            should_notify = transition_messages_enabled_from_env()
        if should_notify and not dry_run and result.get("task", {}).get("status") == "in_progress":
            result["transition_notification"] = play_transition_message("in_progress")

        return result

    def complete_task(
        self,
        task_id: str,
        actor: str,
        checks: list[str],
        notes: str | None = None,
        file_updates: list[dict[str, str]] | None = None,
        issue_id: str | None = None,
        fixes: str | None = None,
        notify_transition: bool | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        if not checks:
            raise ESAAError("INVALID_ARGUMENT", "complete requires at least one --check")

        task = self.task_state(task_id)["task"]

        activity_event: dict[str, Any] = {
            "action": "complete",
            "task_id": task_id,
            "prior_status": "in_progress",
            "notes": notes or f"Deterministic complete for {task_id}",
            "verification": {"checks": checks},
        }

        resolved_issue_id = issue_id or task.get("issue_id")

        resolved_fixes = fixes or task.get("fixes")

        if resolved_issue_id:
            activity_event["issue_id"] = resolved_issue_id

        if resolved_fixes:
            activity_event["fixes"] = resolved_fixes

        output: dict[str, Any] = {"activity_event": activity_event}

        if file_updates is not None:
            output["file_updates"] = file_updates

        result = self._submit_command(output, actor=actor, task_id=task_id, dry_run=dry_run)
        should_notify = notify_transition
        if should_notify is None:
            should_notify = transition_messages_enabled_from_env()
        if should_notify and not dry_run and result.get("task", {}).get("status") == "review":
            result["transition_notification"] = play_transition_message("review")
        return result

    def review_task(
        self,
        task_id: str,
        actor: str,
        decision: str,
        tasks: list[str] | None = None,
        review_mode: str | None = None,
        notify_completion: bool | None = None,
        notify_transition: bool | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        previous_status = self.task_state(task_id)["task"]["status"]
        activity_event = {
            "action": "review",
            "task_id": task_id,
            "prior_status": "review",
            "decision": decision,
            "tasks": tasks or [task_id],
        }
        if review_mode:
            activity_event["review_mode"] = review_mode

        result = self._submit_command(
            {"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run
        )
        should_notify_transition = notify_transition
        if should_notify_transition is None:
            should_notify_transition = transition_messages_enabled_from_env()

        should_notify_completion = notify_completion
        if should_notify_completion is None:
            should_notify_completion = completion_alarm_enabled_from_env()

        final_status = result.get("task", {}).get("status")
        if (
            not dry_run
            and previous_status == "review"
            and final_status in {"in_progress", "done"}
            and (should_notify_transition or (should_notify_completion and final_status == "done"))
        ):
            notification = play_transition_message(final_status)
            result["transition_notification"] = notification
            if final_status == "done" and should_notify_completion:
                result["completion_notification"] = notification
        return result

    def report_issue(
        self,
        task_id: str,
        actor: str,
        issue_id: str,
        severity: str,
        title: str,
        symptom: str,
        repro_steps: list[str],
        fixes: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        if not repro_steps:
            raise ESAAError("INVALID_ARGUMENT", "issue report requires at least one --repro-step")

        task = self.task_state(task_id)["task"]

        prior_status = task["status"]

        activity_event: dict[str, Any] = {
            "action": "issue.report",
            "task_id": task_id,
            "prior_status": prior_status,
            "issue_id": issue_id,
            "severity": severity,
            "title": title,
            "evidence": {"symptom": symptom, "repro_steps": repro_steps},
        }

        if fixes:
            activity_event["fixes"] = fixes

        return self._submit_command(
            {"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run
        )

    def reject_output(
        self,
        task_id: str,
        error_code: str,
        source_action: str,
        message: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        event = make_event(
            next_event_seq(parse_event_store(self.root)),
            actor="orchestrator",
            action="output.rejected",
            payload={
                "task_id": task_id,
                "error_code": error_code,
                "message": message,
                "source_action": source_action,
            },
        )

        return self._commit_orchestrator_events([event], dry_run=dry_run)

    def create_hotfix(
        self,
        issue_id: str,
        fixes: str,
        scope_patch: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        events = parse_event_store(self.root)

        # M-03: validacao agora ocorre dentro de build_hotfix_event.
        event = build_hotfix_event(
            events,
            {
                "issue_id": issue_id,
                "fixes": fixes,
                "scope_patch": scope_patch or ["src/hotfix/"],
            },
        )

        if event is None:
            raise ESAAError("HOTFIX_ALREADY_EXISTS", f"hotfix already exists for issue {issue_id}")

        return self._commit_orchestrator_events([event], dry_run=dry_run)

    def resolve_issue(
        self,
        issue_id: str,
        hotfix_task_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:

        resolution: dict[str, Any] = {"status": "resolved_by_command"}

        if hotfix_task_id:
            resolution["hotfix_task_id"] = hotfix_task_id

        event = make_event(
            next_event_seq(parse_event_store(self.root)),
            actor="orchestrator",
            action="issue.resolve",
            payload={"issue_id": issue_id, "resolution": resolution},
        )

        return self._commit_orchestrator_events([event], dry_run=dry_run)

    def _admit_planned_task_if_needed(self, task_id: str) -> dict[str, Any] | None:

        events = parse_event_store(self.root)

        roadmap, _, _ = materialize(events)

        if any(task["task_id"] == task_id for task in roadmap["tasks"]):
            return None

        planned = find_planned_plugin_task(self.root, task_id)

        if planned is None:
            return None

        event = make_event(
            next_event_seq(events),
            actor="orchestrator",
            action="task.create",
            payload=planned,
        )

        return self._commit_orchestrator_events([event], dry_run=False)
