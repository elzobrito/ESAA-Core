from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .conflicts import conflict_between_sets, explain_conflict, normalize_write_set
from .edits import resolve_edit_updates
from .errors import ESAAError
from .events import build_hotfix_event, build_issue_resolve_event, make_event
from .external_effects import resolve_external_file_updates
from .file_effects import (
    commit_staged,
    compute_file_metadata,
    discard_staged,
    stage_and_compute,
)
from .projector import materialize
from .provenance import resolve_runner
from .runtime_policy import is_blocked_by_max_attempts
from .seeds import all_tasks_done
from .store import (
    load_agent_contract,
    load_agent_result_schema,
    next_event_seq,
    parse_event_store,
)
from .utils import normalize_rel_path
from .validator import (
    validate_agent_output,
    validate_file_update_resource_limits,
    validate_resolved_file_boundaries,
    validate_unique_file_update_paths,
)


def _normalize_file_updates(root: Path, file_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        {"path": normalize_rel_path(item["path"]), "content": item["content"]}
        for item in resolve_edit_updates(root, file_updates)
    ]
    validate_unique_file_update_paths(normalized)
    return normalized


def _dry_run_file_effects(root: Path, file_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for item in file_updates:
        extra = {
            "effect_scope": item.get("_esaa_effect_scope", "workspace"),
            "source_path": item.get("_esaa_source_path", item["path"]),
            "target": item.get("_esaa_target"),
            "target_root": item.get("_esaa_target_root"),
            "target_path": item.get("_esaa_target_path"),
        }
        meta = compute_file_metadata(
            root,
            item["path"],
            item["content"],
            final_abs_path=item.get("_esaa_final_abs_path"),
            extra=extra,
        )
        meta["artifact_sha256"] = None
        meta["artifact_path"] = None
        effects.append(meta)
    return effects


def _file_write_payload(task_id: str, effects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "files": [effect["path"] for effect in effects],
        "effects": effects,
    }


class SubmissionMixin:
    def _submit_command(
        self,
        output: dict[str, Any],
        actor: str,
        task_id: str,
        dry_run: bool,
    ) -> dict[str, Any]:

        result = self.submit(output, actor=actor, dry_run=dry_run)

        if not dry_run:

            result["task"] = self.task_state(task_id)["task"]

        return result

    def submit(self, agent_output: dict[str, Any], actor: str, dry_run: bool = False) -> dict[str, Any]:

        events = parse_event_store(self.root)

        contract = load_agent_contract(self.root)

        schema = load_agent_result_schema(self.root)

        roadmap, _, _ = materialize(events)

        activity_event = agent_output.get("activity_event", {})

        task_id = activity_event.get("task_id")

        if not task_id:

            raise ESAAError("SCHEMA_INVALID", "activity_event.task_id is required")

        task = None

        for t in roadmap["tasks"]:

            if t["task_id"] == task_id:

                task = t

                break

        if not task:

            raise ESAAError("TASK_NOT_FOUND", f"task_id not found: {task_id}")

        # R2: bloqueia se ja atingiu max_attempts

        policy = self._policy()

        max_attempts = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)

        if is_blocked_by_max_attempts(events, task_id, max_attempts):

            raise ESAAError(
                "MAX_ATTEMPTS_EXCEEDED", f"task {task_id} reached {max_attempts} penalizing rejections"
            )

        # G08/PROV-02: valida runner contra o registro do swarm quando strict
        from .runtime_policy import validate_runner_id

        validate_runner_id(resolve_runner()["runner_id"], root=self.root, policy=policy)

        current_seq = next_event_seq(events)
        new_events: list[dict[str, Any]] = []
        files_written = 0
        staged_file_effects: list[dict[str, Any]] = []
        effects_for_result: list[dict[str, Any]] = []

        try:
            validated_event, file_updates = validate_agent_output(agent_output, schema, contract, task)
            file_updates = _normalize_file_updates(self.root, file_updates)
            validate_file_update_resource_limits(file_updates, policy)
            file_updates = resolve_external_file_updates(self.root, task, file_updates)
            validate_resolved_file_boundaries(file_updates, contract, task)
            # FIX-1807: review_authorization=qa_role -> resolve role e injeta _reviewer_role no payload
            if validated_event["action"] == "review":
                from .runtime_policy import resolve_role, review_authorization_mode

                mode = review_authorization_mode(policy)

                role = resolve_role(actor, root=self.root)

                if mode == "qa_role":

                    if role not in {"qa", "orchestrator"}:

                        raise ESAAError(
                            "REVIEW_ROLE_VIOLATION",
                            f"actor {actor} role={role} not authorized to review (qa_role mode)",
                        )

                    validated_event["_reviewer_role"] = role

            agent_event = make_event(
                current_seq, actor=actor, action=validated_event["action"], payload=validated_event
            )

            candidate_events = [agent_event]

            _ = materialize(events + candidate_events)

            if file_updates:
                if dry_run:
                    effects = _dry_run_file_effects(self.root, file_updates)
                else:
                    staged_file_effects, effects = stage_and_compute(self.root, file_updates)
                write_event = make_event(
                    current_seq + 1,
                    actor="orchestrator",
                    action="orchestrator.file.write",
                    payload=_file_write_payload(task_id, effects),
                )
                effects_for_result = effects
                candidate_events.append(write_event)
                _ = materialize(events + candidate_events)
                files_written += len(file_updates)

            if validated_event["action"] == "issue.report":
                # M-03: validacao interna em build_hotfix_event (raise_on_invalid=True).
                hotfix_event = build_hotfix_event(events + candidate_events, validated_event)
                if hotfix_event:
                    candidate_events.append(hotfix_event)
                    _ = materialize(events + candidate_events)

            if validated_event["action"] == "review":

                resolve_event = build_issue_resolve_event(events + candidate_events, task, validated_event)

                if resolve_event:

                    candidate_events.append(resolve_event)

                    _ = materialize(events + candidate_events)

            new_events.extend(candidate_events)
        except Exception:
            discard_staged(staged_file_effects)
            raise

        all_events = events + new_events

        verify_start = make_event(
            next_event_seq(all_events), actor="orchestrator", action="verify.start", payload={"strict": True}
        )

        all_events.append(verify_start)

        new_events.append(verify_start)

        final_roadmap, final_issues, final_lessons = materialize(all_events)

        if all_tasks_done(final_roadmap["tasks"]) and final_roadmap["meta"]["run"]["status"] != "success":

            run_end = make_event(
                next_event_seq(all_events),
                actor="orchestrator",
                action="run.end",
                payload={"status": "success"},
            )

            all_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(all_events)

        verify_ok = make_event(
            next_event_seq(all_events),
            actor="orchestrator",
            action="verify.ok",
            payload={"projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]},
        )

        all_events.append(verify_ok)

        new_events.append(verify_ok)

        final_roadmap, final_issues, final_lessons = materialize(all_events)

        if not dry_run:
            try:
                self._append_events_transactionally(events, new_events)
                commit_staged(self.root, staged_file_effects)
            except Exception:
                discard_staged(staged_file_effects)
                raise

        result = {
            "status": "dry_run" if dry_run else "accepted",
            "actor": actor,
            "task_id": task_id,
            "action": validated_event["action"],
            "events_appended": len(new_events),
            "files_written": files_written,
            "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],
            "verify_status": final_roadmap["meta"]["run"]["verify_status"],
            "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"],
        }
        if dry_run:
            result["would_append_events"] = len(new_events)
            result["simulated_last_event_seq"] = result["last_event_seq"]
            result["simulated_projection_hash_sha256"] = result["projection_hash_sha256"]
            external_effects = [
                {
                    "target": effect.get("target"),
                    "source": effect.get("source_path") or effect.get("path"),
                    "resolved_path": effect.get("absolute_path"),
                    "target_path": effect.get("target_path"),
                    "allowed": True,
                }
                for effect in effects_for_result
                if effect.get("effect_scope") == "external"
            ]
            if external_effects:
                result["external_effects"] = external_effects
        return result

    def process(self, dry_run: bool = False) -> dict[str, Any]:

        inbox = self.root / ".roadmap" / "inbox"

        if not inbox.exists():

            return {"processed": 0, "accepted": 0, "rejected": 0, "results": []}

        done_dir = inbox / "done"

        rejected_dir = inbox / "rejected"

        done_dir.mkdir(parents=True, exist_ok=True)

        rejected_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(inbox.glob("*.json"))

        results: list[dict[str, Any]] = []

        accepted = 0

        rejected = 0

        for filepath in files:

            name = filepath.stem

            if "__" in name:

                actor, _task_id = name.split("__", 1)

            else:

                actor = "agent-external"

            try:

                agent_output = json.loads(filepath.read_text(encoding="utf-8"))

                result = self.submit(agent_output, actor=actor, dry_run=dry_run)

                results.append(result)

                accepted += 1

                if not dry_run:

                    filepath.rename(done_dir / filepath.name)

            except (ESAAError, json.JSONDecodeError) as exc:

                error_info = {"status": "rejected", "file": filepath.name, "error": str(exc)}

                if isinstance(exc, ESAAError):

                    error_info["error_code"] = exc.code

                    error_info["error"] = exc.message

                results.append(error_info)

                rejected += 1

                if not dry_run:

                    filepath.rename(rejected_dir / filepath.name)

        return {"processed": len(files), "accepted": accepted, "rejected": rejected, "results": results}

    def _accept_agent_output(
        self,
        events: list[dict[str, Any]],
        new_events: list[dict[str, Any]],
        task: dict[str, Any],
        output: dict[str, Any],
        schema: dict[str, Any],
        contract: dict[str, Any],
        dry_run: bool,
        wave_write_set: list[str] | None = None,
        staged_file_effects: list[dict[str, Any]] | None = None,
    ) -> int:
        current_seq = next_event_seq(events + new_events)
        activity_event, file_updates = validate_agent_output(output, schema, contract, task)
        file_updates = _normalize_file_updates(self.root, file_updates)
        validate_file_update_resource_limits(file_updates, self._policy())
        file_updates = resolve_external_file_updates(self.root, task, file_updates)
        validate_resolved_file_boundaries(file_updates, contract, task)
        known_roadmap, _, _ = materialize(events + new_events)
        known_task_ids = {item["task_id"] for item in known_roadmap.get("tasks", [])}
        candidate_events: list[dict[str, Any]] = []
        if task["task_id"] not in known_task_ids:
            task_payload = {
                "task_id": task["task_id"],
                "task_kind": task["task_kind"],
                "title": task["title"],
                "description": task.get("description", task["title"]),
                "depends_on": list(task.get("depends_on", [])),
                "targets": list(task.get("targets", [])),
                "outputs": task.get("outputs", {"files": []}),
            }
            candidate_events.append(
                make_event(current_seq, actor="orchestrator", action="task.create", payload=task_payload)
            )
            current_seq += 1
        agent_event = make_event(
            current_seq, actor=self.adapter.agent_id, action=activity_event["action"], payload=activity_event
        )
        candidate_events.append(agent_event)
        _ = materialize(events + new_events + candidate_events)

        files_written = 0
        local_staged: list[dict[str, Any]] = []
        accepted_write_set: list[str] = []
        try:
            if file_updates:
                current_write_set = normalize_write_set(item["path"] for item in file_updates)
                if wave_write_set is not None and conflict_between_sets(wave_write_set, current_write_set):
                    conflict = explain_conflict(wave_write_set, current_write_set)
                    raise ESAAError(
                        "WRITE_CONFLICT", json.dumps(conflict, ensure_ascii=False, sort_keys=True)
                    )

                if dry_run:
                    effects = _dry_run_file_effects(self.root, file_updates)
                else:
                    local_staged, effects = stage_and_compute(self.root, file_updates)

                write_event = make_event(
                    next_event_seq(events + new_events + candidate_events),
                    actor="orchestrator",
                    action="orchestrator.file.write",
                    payload=_file_write_payload(task["task_id"], effects),
                )
                candidate_events.append(write_event)
                _ = materialize(events + new_events + candidate_events)
                files_written += len(file_updates)
                accepted_write_set = current_write_set

            if activity_event["action"] == "issue.report":
                # M-03: validacao interna em build_hotfix_event (raise_on_invalid=True).
                hotfix_event = build_hotfix_event(events + new_events + candidate_events, activity_event)
                if hotfix_event:
                    candidate_events.append(hotfix_event)
                    _ = materialize(events + new_events + candidate_events)

            if activity_event["action"] == "review":
                resolve_event = build_issue_resolve_event(
                    events + new_events + candidate_events, task, activity_event
                )
                if resolve_event:
                    candidate_events.append(resolve_event)
                    _ = materialize(events + new_events + candidate_events)

            if staged_file_effects is not None:
                staged_file_effects.extend(local_staged)
            if wave_write_set is not None:
                wave_write_set.extend(accepted_write_set)
            new_events.extend(candidate_events)
            return files_written
        except Exception:
            discard_staged(local_staged)
            raise
