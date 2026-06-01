from __future__ import annotations



import json

from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone

from pathlib import Path

from typing import Any



from jsonschema import Draft202012Validator, FormatChecker



from .adapters.base import AgentAdapter

from .adapters.mock import MockAgentAdapter

from .conflicts import conflict_between_sets, explain_conflict, normalize_write_set

from .constants import ESAA_VERSION, SCHEMA_VERSION

from .dispatch import build_minimal_context

from .errors import CorruptedStoreError, ESAAError
from .file_effects import (
    commit_staged,
    compute_file_metadata,
    discard_staged,
    recover_file_effects as recover_file_effects_from_events,
    stage_and_compute,
)
from .metrics import compute_metrics
from .projector import materialize
from .plugins import load_active_roadmap_tasks

from .runner_metrics import normalize_runner_metrics

from .runtime_policy import (

    attempt_expired,

    is_blocked_by_max_attempts,

    is_in_cooldown,

    load_policy,

    parse_duration,

)

from .store import (

    append_events,
    append_transactional,
    ensure_event_store,

    load_agent_contract,

    load_agent_result_schema,

    load_roadmap,

    next_event_seq,

    parse_event_store,

    require_task,

    save_issues,

    save_lessons,

    save_roadmap,

)

from .state_machine import allowed_actions_for, expected_action_for

from .utils import ensure_parent, normalize_rel_path, utc_now_iso

from .validator import validate_agent_output





# FIX-1813: lessons baseline reseed canonicas â€” reconstrutiveis por replay.

BASELINE_LESSONS: list[dict[str, Any]] = [
    {

        "lesson_id": "LES-0001",

        "status": "active",

        "title": "Nunca colapsar claim + complete",

        "mistake": "Agente emitiu complete sem claim previo; tarefa nao transita corretamente.",

        "rule": "Cada invocacao emite exatamente uma action. claim e complete sao outputs separados.",

        "scope": {"task_kinds": ["spec", "impl", "qa"]},

        "enforcement": {"mode": "reject", "applies_to": "workflow_gate"},

        "source_refs": [{"type": "gate", "ref": "WG-001"}, {"type": "gate", "ref": "WG-005"}],

    },

    {

        "lesson_id": "LES-0002",

        "status": "active",

        "title": "file_updates exige action=complete",

        "mistake": "file_updates emitido com claim/review/issue.report; nao deveria existir.",

        "rule": "Todo file_updates DEVE acompanhar action=complete; outros actions sao rejeitados.",

        "scope": {"task_kinds": ["spec", "impl", "qa"]},

        "enforcement": {"mode": "reject", "applies_to": "output_contract"},

        "source_refs": [{"type": "gate", "ref": "WG-002"}],

    },

    {

        "lesson_id": "LES-0003",

        "status": "active",

        "title": "prior_status obrigatorio e coerente",

        "mistake": "prior_status omitido ou divergente do status real do roadmap.",

        "rule": "prior_status e obrigatorio em todo output e deve refletir o status do roadmap.",

        "scope": {"task_kinds": ["spec", "impl", "qa"]},

        "enforcement": {"mode": "require_field", "applies_to": "output_contract"},

        "source_refs": [{"type": "gate", "ref": "WG-003"}],

    },

]


def _normalize_file_updates(file_updates: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"path": normalize_rel_path(item["path"]), "content": item["content"]}
        for item in file_updates
    ]


def _dry_run_file_effects(root: Path, file_updates: list[dict[str, str]]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for item in file_updates:
        meta = compute_file_metadata(root, item["path"], item["content"])
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


def _projection_hash(events: list[dict[str, Any]]) -> str:
    roadmap, _, _ = materialize(events)
    return roadmap["meta"]["run"]["projection_hash_sha256"]


class ESAAService:
    def __init__(self, root: Path, adapter: AgentAdapter | None = None) -> None:

        self.root = root

        self.adapter = adapter or MockAgentAdapter()

        self._policy_cache: dict[str, Any] | None = None



    def _policy(self) -> dict[str, Any]:

        if self._policy_cache is None:

            self._policy_cache = load_policy(self.root)

        return self._policy_cache



    def init(self, run_id: str = "RUN-0001", master_correlation_id: str = "CID-ESAA-INIT", force: bool = False) -> dict[str, Any]:

        roadmap_dir = self.root / ".roadmap"

        roadmap_dir.mkdir(parents=True, exist_ok=True)



        if not force and (self.root / ".roadmap/activity.jsonl").exists():

            existing = (self.root / ".roadmap/activity.jsonl").read_text(encoding="utf-8").strip()

            if existing:

                raise ESAAError("INIT_BLOCKED", "event store already contains events; use --force to reinitialize")



        for rel in ("docs/spec", "docs/qa", "src", "tests"):

            (self.root / rel).mkdir(parents=True, exist_ok=True)



        seed = load_plugin_seeds(self.root)

        run_start_payload: dict[str, Any] = {

            "run_id": run_id,

            "status": "initialized",

            "master_correlation_id": master_correlation_id,

            "baseline_id": "B-000",

        }

        if seed:

            tasks = seed["tasks"]

            if seed.get("project_name"):

                run_start_payload["project_name"] = seed["project_name"]

            if seed.get("audit_scope"):

                run_start_payload["audit_scope"] = seed["audit_scope"]

        else:

            tasks = seed_tasks()



        events: list[dict[str, Any]] = []

        seq = 1

        events.append(

            make_event(seq, actor="orchestrator", action="run.start", payload=run_start_payload)

        )

        seq += 1

        for task in tasks:

            events.append(make_event(seq, actor="orchestrator", action="task.create", payload=task))

            seq += 1



        # FIX-1813: baseline lessons reseed â€” emite orchestrator.view.mutate com lessons

        # canonicas. O projetor reconstroi lessons.json a partir deste evento (R1-fix).

        events.append(

            make_event(seq, actor="orchestrator", action="orchestrator.view.mutate",

                       payload={

                           "target": "lessons",

                           "change": "baseline_reseed",

                           "lessons": BASELINE_LESSONS,

                       })

        )

        seq += 1



        events.append(

            make_event(seq, actor="orchestrator", action="verify.start", payload={"strict": True})

        )

        seq += 1



        roadmap_preview, _, _ = materialize(events)

        events.append(

            make_event(seq, actor="orchestrator", action="verify.ok",

                       payload={"projection_hash_sha256": roadmap_preview["meta"]["run"]["projection_hash_sha256"]})

        )



        path = ensure_event_store(self.root)

        path.write_text("", encoding="utf-8")

        append_events(self.root, events)

        roadmap, issues, lessons = materialize(events)

        save_roadmap(self.root, roadmap)

        save_issues(self.root, issues)

        save_lessons(self.root, lessons)

        return {

            "run_id": run_id,

            "events_written": len(events),

            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],

            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],

        }



    def project(self) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, issues, lessons = materialize(events)

        save_roadmap(self.root, roadmap)

        save_issues(self.root, issues)

        save_lessons(self.root, lessons)

        return {

            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],

            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],

            "tasks": len(roadmap["tasks"]),

            "issues": len(issues["issues"]),

            "lessons": len(lessons["lessons"]),

        }



    def verify(self) -> dict[str, Any]:

        try:

            events = parse_event_store(self.root)

            projected, _, _ = materialize(events)

        except CorruptedStoreError as exc:

            return {"verify_status": "corrupted", "error_code": exc.code,

                    "error_message": exc.message, "last_event_seq": None,

                    "projection_hash_sha256": None}



        stored = load_roadmap(self.root)

        if stored is None:

            return {"verify_status": "mismatch", "reason": "roadmap_missing",

                    "last_event_seq": projected["meta"]["run"]["last_event_seq"],

                    "projection_hash_sha256": projected["meta"]["run"]["projection_hash_sha256"]}



        computed_hash = projected["meta"]["run"]["projection_hash_sha256"]

        stored_hash = stored.get("meta", {}).get("run", {}).get("projection_hash_sha256")

        computed_seq = projected["meta"]["run"]["last_event_seq"]

        stored_seq = stored.get("meta", {}).get("run", {}).get("last_event_seq")



        if computed_hash == stored_hash and computed_seq == stored_seq:

            return {"verify_status": "ok", "last_event_seq": computed_seq,

                    "projection_hash_sha256": computed_hash}

        return {"verify_status": "mismatch", "last_event_seq": computed_seq,

                "projection_hash_sha256": computed_hash,

                "stored_last_event_seq": stored_seq,

                "stored_projection_hash_sha256": stored_hash}



    def metrics(self) -> dict[str, Any]:
        return compute_metrics(parse_event_store(self.root))

    def recover_file_effects(self, dry_run: bool = False) -> dict[str, Any]:
        return recover_file_effects_from_events(self.root, parse_event_store(self.root), dry_run=dry_run)

    def _append_events_transactionally(
        self,
        base_events: list[dict[str, Any]],
        new_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        expected_first_seq = next_event_seq(base_events)
        expected_hash = _projection_hash(base_events)

        def build_events(current_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            current_first_seq = next_event_seq(current_events)
            for offset, event in enumerate(new_events):
                expected_seq = current_first_seq + offset
                if event["event_seq"] != expected_seq:
                    raise ESAAError(
                        "EVENT_SEQ_NON_MONOTONIC",
                        f"expected event_seq={expected_seq}, got {event['event_seq']}",
                    )
            return list(new_events)

        return append_transactional(
            self.root,
            build_events,
            expected_first_seq=expected_first_seq,
            expected_projection_hash=expected_hash,
        )

    def _validate_roadmap_projection_schema(self, roadmap: dict[str, Any]) -> None:
        schema_path = self.root / ".roadmap" / "roadmap.schema.json"
        if not schema_path.exists():

            raise ESAAError("SCHEMA_MISSING", "roadmap.schema.json is required for task create")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        errors = sorted(

            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(roadmap),

            key=lambda error: list(error.absolute_path),

        )

        if errors:

            error = errors[0]

            path = "/".join(str(part) for part in error.absolute_path) or "<root>"

            raise ESAAError("SCHEMA_INVALID", f"roadmap.schema.json {path}: {error.message}")



    def record_runner_metrics(self, payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:

        normalized = normalize_runner_metrics(payload)

        event = make_event(

            next_event_seq(parse_event_store(self.root)),

            actor="orchestrator",

            action="runner.metrics",

            payload=normalized,

        )

        return self._commit_orchestrator_events([event], dry_run=dry_run)



    def create_task(

        self,

        task_id: str,

        task_kind: str,

        title: str,

        description: str | None = None,

        outputs: list[str] | None = None,

        depends_on: list[str] | None = None,

        targets: list[str] | None = None,

        dry_run: bool = False,

    ) -> dict[str, Any]:

        task_id = task_id.strip()

        title = title.strip()

        description = description.strip() if description is not None else None

        outputs = [item.strip() for item in (outputs or [])]

        depends_on = [item.strip() for item in (depends_on or [])]

        targets = [item.strip() for item in (targets or [])]



        if task_kind not in {"spec", "impl", "qa"}:

            raise ESAAError("SCHEMA_INVALID", f"invalid task_kind: {task_kind}")

        if not task_id:

            raise ESAAError("SCHEMA_INVALID", "task_id is required")

        if not title:

            raise ESAAError("SCHEMA_INVALID", "title is required")



        events = parse_event_store(self.root)

        roadmap, _, _ = materialize(events)

        tasks, _ = tasks_with_planned_plugins(self.root, roadmap["tasks"])

        if any(task["task_id"] == task_id for task in tasks):

            raise ESAAError("DUPLICATE_TASK", f"task already exists: {task_id}")



        payload = {

            "task_id": task_id,

            "task_kind": task_kind,

            "title": title,

            "description": description or title,

            "depends_on": depends_on,

            "targets": targets,

            "outputs": {"files": outputs},

        }

        event = make_event(next_event_seq(events), actor="orchestrator", action="task.create", payload=payload)

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

        if not force:

            raise ESAAError("CLEAR_REQUIRES_FORCE", "activity clear requires --force")



        path = ensure_event_store(self.root)

        raw = path.read_text(encoding="utf-8")

        raw_lines = [line for line in raw.splitlines() if line.strip()]

        parse_error: dict[str, str] | None = None

        try:

            events_removed = len(parse_event_store(self.root))

        except CorruptedStoreError as exc:

            events_removed = len(raw_lines)

            parse_error = {"error_code": exc.code, "error_message": exc.message}



        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

        backup_base = Path(backup_dir)

        backup_name = f"activity-{stamp}.jsonl"

        if backup_base.is_absolute():

            backup_path = backup_base / backup_name

            backup_report = str(backup_path)

        else:

            backup_path = self.root / backup_base / backup_name

            backup_report = str(backup_base / backup_name).replace("\\", "/")



        result: dict[str, Any] = {

            "status": "dry_run" if dry_run else "cleared",

            "event_store": ".roadmap/activity.jsonl",

            "events_removed": events_removed,

            "bytes_removed": len(raw.encode("utf-8")),

            "backup_path": backup_report,

        }

        if parse_error:

            result["parse_error_before_clear"] = parse_error

        if dry_run:

            return result



        ensure_parent(backup_path)

        backup_path.write_text(raw, encoding="utf-8")

        seed_events = [
            make_event(
                1,
                actor="orchestrator",
                action="orchestrator.view.mutate",
                payload={
                    "target": "lessons",
                    "change": "baseline_reseed",
                    "lessons": BASELINE_LESSONS,
                },
            ),
            make_event(2, actor="orchestrator", action="verify.start", payload={"strict": True}),
        ]
        preview_roadmap, _, _ = materialize(seed_events)
        seed_events.append(
            make_event(
                3,
                actor="orchestrator",
                action="verify.ok",
                payload={"projection_hash_sha256": preview_roadmap["meta"]["run"]["projection_hash_sha256"]},
            )
        )

        path.write_text("", encoding="utf-8")
        append_events(self.root, seed_events)



        roadmap, issues, lessons = materialize(seed_events)

        save_roadmap(self.root, roadmap)

        save_issues(self.root, issues)

        save_lessons(self.root, lessons)

        verify = self.verify()

        result.update({

            "last_event_seq": verify["last_event_seq"],

            "verify_status": verify["verify_status"],

            "projection_hash_sha256": verify["projection_hash_sha256"],

        })

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

        return context



    def claim_task(self, task_id: str, actor: str, notes: str | None = None, dry_run: bool = False) -> dict[str, Any]:

        admission = None if dry_run else self._admit_planned_task_if_needed(task_id)

        activity_event: dict[str, Any] = {

            "action": "claim",

            "task_id": task_id,

            "prior_status": "todo",

        }

        if notes:

            activity_event["notes"] = notes

        result = self._submit_command({"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run)

        if admission:

            result["admission"] = {

                "action": "task.create",

                "task_id": task_id,

                "events_appended": admission["events_appended"],

            }

            result["events_appended_total"] = result["events_appended"] + admission["events_appended"]

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

        return self._submit_command(output, actor=actor, task_id=task_id, dry_run=dry_run)



    def review_task(

        self,

        task_id: str,

        actor: str,

        decision: str,

        tasks: list[str] | None = None,

        dry_run: bool = False,

    ) -> dict[str, Any]:

        activity_event = {

            "action": "review",

            "task_id": task_id,

            "prior_status": "review",

            "decision": decision,

            "tasks": tasks or [task_id],

        }

        return self._submit_command({"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run)



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

        return self._submit_command({"activity_event": activity_event}, actor=actor, task_id=task_id, dry_run=dry_run)



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



    def _commit_orchestrator_events(self, candidate_events: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:

        if not candidate_events:

            raise ESAAError("INVALID_ARGUMENT", "at least one orchestrator event is required")

        events = parse_event_store(self.root)

        expected_seq = next_event_seq(events)

        if candidate_events[0]["event_seq"] != expected_seq:

            raise ESAAError("EVENT_SEQ_NON_MONOTONIC", f"expected event_seq={expected_seq}")



        new_events = list(candidate_events)

        all_events = events + new_events

        final_roadmap, final_issues, final_lessons = materialize(all_events)



        if all_tasks_done(final_roadmap["tasks"]) and final_roadmap["meta"]["run"]["status"] != "success":

            run_end = make_event(next_event_seq(all_events), actor="orchestrator", action="run.end", payload={"status": "success"})

            all_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(all_events)



        verify_start = make_event(next_event_seq(all_events), actor="orchestrator", action="verify.start", payload={"strict": True})

        all_events.append(verify_start)

        new_events.append(verify_start)

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
            self._append_events_transactionally(events, new_events)


        first = candidate_events[0]

        payload = first["payload"]

        result = {

            "status": "dry_run" if dry_run else "accepted",

            "actor": first["actor"],

            "action": first["action"],

            "event_id": first["event_id"],

            "events_appended": len(new_events),

            "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],

            "verify_status": final_roadmap["meta"]["run"]["verify_status"],

            "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"],

        }
        if dry_run:
            result["would_append_events"] = len(new_events)
            result["simulated_last_event_seq"] = result["last_event_seq"]
            result["simulated_projection_hash_sha256"] = result["projection_hash_sha256"]

        for key in ("task_id", "issue_id", "error_code", "source_action"):

            if key in payload:

                result[key] = payload[key]

        return result



    def eligible(self) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, _, _ = materialize(events)

        tasks, task_sources = tasks_with_planned_plugins(self.root, roadmap["tasks"])

        # R2: filtra tarefas bloqueadas por max_attempts ou em cooldown

        policy = self._policy()

        max_attempts = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)

        cooldown = parse_duration(policy.get("attempt_limits", {}).get("cooldown_between_attempts", "PT2M"))

        now = datetime.now(timezone.utc)



        elig = []

        for t in list_eligible_tasks(tasks):

            if is_blocked_by_max_attempts(events, t["task_id"], max_attempts):

                continue

            if is_in_cooldown(events, t["task_id"], now, cooldown):

                continue

            elig.append(t)

        groups = parallel_groups(elig)

        max_parallel = max((len(g) for g in groups), default=0)

        return {

            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],

            "eligible_count": len(elig),

            "max_parallel": max_parallel,

            "eligible": [

                {"task_id": t["task_id"], "task_kind": t["task_kind"], "title": t["title"],

                 "outputs": t.get("outputs", {}).get("files", []),

                 "depends_on": t.get("depends_on", []),

                 "source": task_sources.get(t["task_id"], "event_store")}

                for t in elig

            ],

            "parallel_groups": groups,

        }



    def replay(self, until: str | None = None, write_views: bool = True) -> dict[str, Any]:

        events = parse_event_store(self.root)

        selected = events

        if until:

            if until.isdigit():

                seq_limit = int(until)

                selected = [ev for ev in events if int(ev["event_seq"]) <= seq_limit]

            else:

                out: list[dict[str, Any]] = []

                for event in events:

                    out.append(event)

                    if event["event_id"] == until:

                        break

                selected = out

        roadmap, issues, lessons = materialize(selected)

        if write_views:

            save_roadmap(self.root, roadmap)

            save_issues(self.root, issues)

            save_lessons(self.root, lessons)

        return {"events_replayed": len(selected),

                "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],

                "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],

                "verify_status": "ok"}



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

            raise ESAAError("MAX_ATTEMPTS_EXCEEDED",

                            f"task {task_id} reached {max_attempts} penalizing rejections")



        current_seq = next_event_seq(events)
        new_events: list[dict[str, Any]] = []
        files_written = 0
        staged_file_effects: list[dict[str, Any]] = []

        try:
            validated_event, file_updates = validate_agent_output(agent_output, schema, contract, task)
            file_updates = _normalize_file_updates(file_updates)
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

            agent_event = make_event(current_seq, actor=actor, action=validated_event["action"], payload=validated_event)

            candidate_events = [agent_event]

            _ = materialize(events + candidate_events)

            if file_updates:
                if dry_run:
                    effects = _dry_run_file_effects(self.root, file_updates)
                else:
                    staged_file_effects, effects = stage_and_compute(self.root, file_updates)
                write_event = make_event(
                    current_seq + 1, actor="orchestrator", action="orchestrator.file.write",
                    payload=_file_write_payload(task_id, effects)
                )
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

        verify_start = make_event(next_event_seq(all_events), actor="orchestrator", action="verify.start", payload={"strict": True})

        all_events.append(verify_start)

        new_events.append(verify_start)



        final_roadmap, final_issues, final_lessons = materialize(all_events)



        if all_tasks_done(final_roadmap["tasks"]) and final_roadmap["meta"]["run"]["status"] != "success":

            run_end = make_event(next_event_seq(all_events), actor="orchestrator", action="run.end", payload={"status": "success"})

            all_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(all_events)



        verify_ok = make_event(next_event_seq(all_events), actor="orchestrator", action="verify.ok",

                               payload={"projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]})

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


        result = {"status": "dry_run" if dry_run else "accepted", "actor": actor, "task_id": task_id,

                  "action": validated_event["action"], "events_appended": len(new_events),

                  "files_written": files_written, "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],

                  "verify_status": final_roadmap["meta"]["run"]["verify_status"],

                  "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]}
        if dry_run:
            result["would_append_events"] = len(new_events)
            result["simulated_last_event_seq"] = result["last_event_seq"]
            result["simulated_projection_hash_sha256"] = result["projection_hash_sha256"]
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
        file_updates = _normalize_file_updates(file_updates)
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
        agent_event = make_event(current_seq, actor=self.adapter.agent_id, action=activity_event["action"], payload=activity_event)
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
                    raise ESAAError("WRITE_CONFLICT", json.dumps(conflict, ensure_ascii=False, sort_keys=True))

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
                resolve_event = build_issue_resolve_event(events + new_events + candidate_events, task, activity_event)
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


    def run(self, steps: int | None = 1, dry_run: bool = False, parallel: int = 1) -> dict[str, Any]:

        if steps is not None and steps < 1:

            raise ESAAError("INVALID_ARGUMENT", "steps must be >= 1")

        if parallel < 1:

            raise ESAAError("INVALID_ARGUMENT", "parallel must be >= 1")



        events = parse_event_store(self.root)

        contract = load_agent_contract(self.root)

        schema = load_agent_result_schema(self.root)

        policy = self._policy()

        max_attempts = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)

        cooldown = parse_duration(policy.get("attempt_limits", {}).get("cooldown_between_attempts", "PT2M"))

        ttl = parse_duration(policy.get("attempt_lifecycle", {}).get("ttl", "PT30M"))



        new_events: list[dict[str, Any]] = []
        staged_file_effects: list[dict[str, Any]] = []
        files_written = 0
        rejected = 0
        executed = 0
        blocked = 0



        last_signature: tuple[tuple[str, str], ...] | None = None

        stall_count = 0

        iteration = 0



        while steps is None or iteration < steps:

            iteration += 1

            roadmap, _, _ = materialize(events + new_events)
            effective_tasks, _ = tasks_with_planned_plugins(self.root, roadmap["tasks"])
            effective_roadmap = {**roadmap, "tasks": effective_tasks}

            now = datetime.now(timezone.utc)



            # R2: filtra elegiveis por attempt_lifecycle

            candidates = [t for t in effective_roadmap["tasks"]

                          if not is_blocked_by_max_attempts(events + new_events, t["task_id"], max_attempts)

                          and not is_in_cooldown(events + new_events, t["task_id"], now, cooldown)]

            wave = select_task_wave(candidates, limit=parallel)

            if not wave:

                break



            # R2: TTL expirado em in_progress -> output.rejected (ATTEMPT_TIMEOUT)

            runnable_wave: list[dict[str, Any]] = []

            for task in wave:

                if task["status"] == "in_progress" and attempt_expired(events + new_events, task["task_id"], now, ttl):

                    seq_to = next_event_seq(events + new_events)

                    timeout_ev = make_event(

                        seq_to, actor="orchestrator", action="output.rejected",

                        payload={"task_id": task["task_id"], "error_code": "ATTEMPT_TIMEOUT",

                                 "message": f"attempt exceeded ttl {ttl}", "source_action": "claim"}

                    )

                    new_events.append(timeout_ev)

                    blocked += 1

                else:

                    runnable_wave.append(task)

            if not runnable_wave:

                continue



            signature = tuple((task["task_id"], task["status"]) for task in runnable_wave)

            if signature == last_signature:

                stall_count += 1

                if stall_count >= 2:

                    break

            else:

                stall_count = 0

            last_signature = signature



            contexts = [(task, build_dispatch_context(effective_roadmap, task, contract, schema=schema)) for task in runnable_wave]



            def execute_context(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None, Exception | None]:

                task, context = item

                try:

                    return task, self.adapter.execute(context), None

                except Exception as exc:  # normalized below into output.rejected

                    return task, None, exc



            if parallel > 1 and len(contexts) > 1:

                with ThreadPoolExecutor(max_workers=min(parallel, len(contexts))) as executor:

                    outputs = list(executor.map(execute_context, contexts))

            else:

                outputs = [execute_context(item) for item in contexts]



            wave_write_set: list[str] = []

            for task, output, execute_error in outputs:

                current_seq = next_event_seq(events + new_events)

                executed += 1

                try:

                    if execute_error is not None:

                        if isinstance(execute_error, ValueError):

                            raise execute_error

                        raise ESAAError("ADAPTER_EXECUTE_FAILED", str(execute_error))

                    assert output is not None

                    files_written += self._accept_agent_output(

                        events,

                        new_events,

                        task,

                        output,

                        schema,
                        contract,
                        dry_run,
                        wave_write_set=wave_write_set,
                        staged_file_effects=staged_file_effects,
                    )
                except ESAAError as exc:

                    rejected += 1

                    reject_event = make_event(

                        current_seq, actor="orchestrator", action="output.rejected",

                        payload={"task_id": task["task_id"], "error_code": exc.code,

                                 "message": exc.message,

                                 "source_action": output.get("activity_event", {}).get("action", "unknown") if isinstance(output, dict) else "unknown"}

                    )

                    new_events.append(reject_event)

                    # R2: se atingiu max_attempts, escalar via issue.report severity=high

                    if is_blocked_by_max_attempts(events + new_events, task["task_id"], max_attempts):

                        esc_seq = next_event_seq(events + new_events)

                        esc = make_event(

                            esc_seq, actor="orchestrator", action="issue.report",

                            payload={"task_id": task["task_id"],

                                     "issue_id": f"ISS-MAXATT-{task['task_id']}",

                                     "severity": "high",

                                     "title": "Max attempts reached",

                                     "evidence": {"symptom": f"{max_attempts} penalizing rejections",

                                                  "repro_steps": [f"task {task['task_id']}", "see output.rejected events"]}}

                        )

                        new_events.append(esc)

                except ValueError as exc:

                    rejected += 1

                    reject_event = make_event(

                        current_seq, actor="orchestrator", action="output.rejected",

                        payload={"task_id": task["task_id"], "error_code": "LLM_PARSE_FAILED",

                                 "message": str(exc), "source_action": "unknown"}

                    )

                    new_events.append(reject_event)



        final_events = events + new_events

        final_roadmap, final_issues, final_lessons = materialize(final_events)

        if all_tasks_done(final_roadmap["tasks"]) and final_roadmap["meta"]["run"]["status"] != "success":

            run_end = make_event(next_event_seq(final_events), actor="orchestrator", action="run.end", payload={"status": "success"})

            final_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(final_events)



        verify_start = make_event(next_event_seq(final_events), actor="orchestrator", action="verify.start", payload={"strict": True})

        final_events.append(verify_start)

        new_events.append(verify_start)



        final_roadmap, final_issues, final_lessons = materialize(final_events)

        verify_ok = make_event(next_event_seq(final_events), actor="orchestrator", action="verify.ok",

                               payload={"projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]})

        final_events.append(verify_ok)

        new_events.append(verify_ok)

        final_roadmap, final_issues, final_lessons = materialize(final_events)



        if not dry_run:
            try:
                self._append_events_transactionally(events, new_events)
                commit_staged(self.root, staged_file_effects)
            except Exception:
                discard_staged(staged_file_effects)
                raise


        result = {"status": "dry_run" if dry_run else "accepted",
                  "steps_requested": steps, "steps_executed": executed, "events_appended": len(new_events),

                  "rejected": rejected, "blocked_by_attempt_lifecycle": blocked,

                  "files_written": files_written, "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],

                  "verify_status": final_roadmap["meta"]["run"]["verify_status"],

                  "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]}
        if dry_run:
            result["would_append_events"] = len(new_events)
            result["simulated_last_event_seq"] = result["last_event_seq"]
            result["simulated_projection_hash_sha256"] = result["projection_hash_sha256"]
        return result





def make_event(event_seq: int, actor: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:

    return {"schema_version": SCHEMA_VERSION, "event_id": f"EV-{event_seq:08d}",

            "event_seq": event_seq, "ts": utc_now_iso(), "actor": actor,

            "action": action, "payload": payload}





def seed_tasks() -> list[dict[str, Any]]:

    return [

        {"task_id": "T-1000", "task_kind": "spec", "title": "Create initial ESAA spec document",

         "description": "Produce the initial specification artifact for the ESAA core baseline.",

         "depends_on": [], "targets": ["spec-core"], "outputs": {"files": ["docs/spec/T-1000.md"]}},

        {"task_id": "T-1010", "task_kind": "impl", "title": "Create initial implementation artifact",

         "description": "Produce the initial implementation artifact that follows the approved specification.",

         "depends_on": ["T-1000"], "targets": ["impl-core"], "outputs": {"files": ["src/T-1010.txt"]}},

        {"task_id": "T-1020", "task_kind": "qa", "title": "Create initial QA report",

         "description": "Produce the initial QA evidence artifact validating the implementation baseline.",

         "depends_on": ["T-1010"], "targets": ["qa-core"], "outputs": {"files": ["docs/qa/T-1020.md"]}},

    ]





def _enrich_audit_description(task: dict[str, Any]) -> str:

    base = task.get("description") or task.get("title", "")

    pointer_parts: list[str] = []

    playbook_ref = task.get("playbook_ref")

    if playbook_ref:

        pointer_parts.append(f"Playbook: {playbook_ref}")

    checks = task.get("checks_covered")

    if checks:

        pointer_parts.append("Checks: " + ", ".join(checks))

    owasp = task.get("owasp_mapping")

    if owasp:

        pointer_parts.append("OWASP/CWE: " + ", ".join(owasp))

    if not pointer_parts:

        return base

    ref = playbook_ref or task["task_id"]

    suffix = " | ".join(pointer_parts)

    return f"{base} | {suffix} | Detalhes executaveis em .roadmap/playbooks.security.json[{ref}]."





def load_plugin_seeds(root: Path) -> dict[str, Any] | None:

    """R9 â€” Loader generico de plugins instalados e compat roadmap.*.json.



    Primeiro carrega roadmaps ativos declarados em `.roadmap/roadmaps.lock.json`.
    Em seguida, por compatibilidade temporaria, descobre arquivos
    `.roadmap/roadmap.*.json` (exceto `roadmap.json`, `roadmap.schema.json` e
    `*.template.json`),

    valida superficialmente, projeta cada tarefa para o subset do schema 0.4.x

    e deduplica por task_id (primeira ocorrencia vence).

    """

    installed_seed = load_active_roadmap_tasks(root)

    plugins = sorted((root / ".roadmap").glob("roadmap.*.json"))

    plugins = [
        p for p in plugins
        if p.name not in {"roadmap.json", "roadmap.schema.json"}
        and not p.name.endswith(".template.json")
    ]

    if not plugins and not installed_seed:

        return None



    project_name: str | None = None

    audit_scope: str | None = None

    seen: set[str] = set()

    tasks: list[dict[str, Any]] = []

    if installed_seed:

        project_name = installed_seed.get("project_name")

        audit_scope = installed_seed.get("audit_scope")

        for task in installed_seed.get("tasks", []):

            tid = task.get("task_id")

            if not tid or tid in seen:

                continue

            seen.add(tid)

            tasks.append(dict(task))



    for plugin in plugins:

        raw = json.loads(plugin.read_text(encoding="utf-8"))

        project = raw.get("project", {}) or {}

        if project_name is None:

            project_name = project.get("name")

        if audit_scope is None:

            audit_scope = project.get("audit_scope")



        for task in raw.get("tasks", []):

            tid = task.get("task_id")

            if not tid or tid in seen:

                continue

            seen.add(tid)

            tasks.append({

                "task_id": tid,

                "task_kind": task["task_kind"],

                "title": task["title"],

                "description": _enrich_audit_description(task),

                "depends_on": list(task.get("depends_on", [])),

                "targets": list(task.get("targets", [])),

                "outputs": task.get("outputs", {"files": []}),

            })



    if not tasks:

        return None

    return {"project_name": project_name, "audit_scope": audit_scope, "tasks": tasks}





def find_planned_plugin_task(root: Path, task_id: str) -> dict[str, Any] | None:

    seed = load_plugin_seeds(root)

    if not seed:

        return None

    for task in seed["tasks"]:

        if task["task_id"] == task_id:

            return dict(task)

    return None





def tasks_with_planned_plugins(root: Path, event_tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:

    """Une tarefas materializadas com tarefas planejadas em roadmap plugins.



    O event store continua sendo a prova do que aconteceu. Tarefas presentes

    apenas em `roadmap.*.json` entram como planejadas para selecao/elegibilidade,

    sem gerar `task.create` ou mutar read models.

    """

    sources = {task["task_id"]: "event_store" for task in event_tasks}

    tasks = list(event_tasks)

    seed = load_plugin_seeds(root)

    if not seed:

        return tasks, sources



    seen = set(sources)

    for task in seed["tasks"]:

        task_id = task["task_id"]

        if task_id in seen:

            continue

        planned = dict(task)

        planned["status"] = "todo"

        planned["immutability"] = {"done_is_immutable": True}

        tasks.append(planned)

        sources[task_id] = "roadmap_plugin"

        seen.add(task_id)

    return tasks, sources





# Backcompat â€” antigos chamadores podem usar load_audit_seed.

def load_audit_seed(root: Path) -> dict[str, Any] | None:

    return load_plugin_seeds(root)





def all_tasks_done(tasks: list[dict[str, Any]]) -> bool:

    return bool(tasks) and all(task["status"] == "done" for task in tasks)





def select_next_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:

    by_id = {task["task_id"]: task for task in tasks}



    for status in ("review", "in_progress"):

        candidates = sorted([task for task in tasks if task["status"] == status], key=lambda item: item["task_id"])

        if candidates:

            return candidates[0]



    todo = sorted([task for task in tasks if task["status"] == "todo"], key=lambda item: item["task_id"])

    for task in todo:

        deps = task.get("depends_on", [])

        if all(by_id[dep]["status"] == "done" for dep in deps if dep in by_id):

            return task

    return None





def select_task_wave(tasks: list[dict[str, Any]], limit: int = 1) -> list[dict[str, Any]]:

    if limit <= 1:

        task = select_next_task(tasks)

        return [task] if task else []



    by_id = {task["task_id"]: task for task in tasks}

    for status in ("review", "in_progress"):

        candidates = sorted([task for task in tasks if task["status"] == status], key=lambda item: item["task_id"])

        if candidates:

            return candidates[:limit]



    eligible = list_eligible_tasks(tasks)

    groups = parallel_groups(eligible)

    if not groups:

        return []

    return [by_id[task_id] for task_id in groups[0][:limit] if task_id in by_id]





def list_eligible_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:

    by_id = {t["task_id"]: t for t in tasks}

    out: list[dict[str, Any]] = []

    for task in sorted(tasks, key=lambda t: t["task_id"]):

        if task["status"] != "todo":

            continue

        deps = task.get("depends_on", [])

        if all(by_id.get(d, {}).get("status") == "done" for d in deps):

            out.append(task)

    return out





def parallel_groups(eligible: list[dict[str, Any]]) -> list[list[str]]:

    groups: list[dict[str, Any]] = []

    for task in eligible:

        files = normalize_write_set(task.get("outputs", {}).get("files", []))

        placed = False

        for g in groups:

            if not conflict_between_sets(g["files"], files):

                g["files"].extend(files)

                g["tasks"].append(task["task_id"])

                placed = True

                break

        if not placed:

            groups.append({"files": list(files), "tasks": [task["task_id"]]})

    return [g["tasks"] for g in groups]





def build_dispatch_context(

    roadmap: dict[str, Any], task: dict[str, Any], contract: dict[str, Any],

    schema: dict[str, Any] | None = None, lessons: list[dict[str, Any]] | None = None,

    issues: list[dict[str, Any]] | None = None,

) -> dict[str, Any]:

    if schema is not None:

        return build_minimal_context(roadmap, task, contract, schema, lessons, issues)

    boundaries = contract["boundaries"]["by_task_kind"][task["task_kind"]]

    return {"task": task, "boundaries": {"read": boundaries.get("read", []), "write": boundaries.get("write", [])},

            "context_pack": {"run": roadmap["meta"]["run"], "project": roadmap["project"]},

            "correlation": {"master_correlation_id": roadmap["meta"].get("master_correlation_id"), "task_id": task["task_id"]}}





def validate_hotfix_request(

    current_events: list[dict[str, Any]],

    issue_payload: dict[str, Any],

) -> tuple[bool, str | None, str | None]:

    """FIX-1811 â€” Valida payload de issue.report para criar hotfix.



    Returns (ok, error_code, message). Se ok=True, hotfix pode ser criado.

    Se ok=False, hotfix NAO deve ser criado e error_code descreve a falha.

    """

    issue_id = issue_payload.get("issue_id")

    fixes = issue_payload.get("fixes")

    if not issue_id:

        return False, "HOTFIX_ISSUE_NOT_FOUND", "issue_id ausente"

    if not fixes:

        return False, "HOTFIX_TARGET_NOT_FOUND", "fixes ausente"



    # Materializa projeÃ§Ã£o atual para inspecionar issues e tasks

    roadmap, issues_view, _ = materialize(current_events)

    tasks_by_id = {t["task_id"]: t for t in roadmap.get("tasks", [])}

    issues_by_id = {i["issue_id"]: i for i in issues_view.get("issues", [])}



    # 1. fixes deve apontar para task existente

    target = tasks_by_id.get(fixes)

    if target is None:

        return False, "HOTFIX_TARGET_NOT_FOUND", f"fixes target {fixes} nao encontrado"



    # 2. Para imutavel-done, target deve estar done

    immutable = target.get("immutability", {}).get("done_is_immutable", False)

    if immutable and target.get("status") != "done":

        return False, "HOTFIX_TARGET_NOT_DONE", (

            f"target {fixes} status={target.get('status')} (imutavel-done exige done)"

        )



    # 3. scope_patch, quando declarado por comando administrativo, nao pode ser vazio.
    # Agent issue.report nao permite scope_patch no schema; nesse caminho o hotfix.create
    # usa o escopo padrao em build_hotfix_event.

    if "scope_patch" in issue_payload:

        scope = issue_payload.get("scope_patch") or []

        if not scope or not isinstance(scope, list):

            return False, "HOTFIX_SCOPE_INVALID", "scope_patch ausente ou vazio"



    # 4. issue deve existir e estar open

    if issue_id not in issues_by_id:

        return False, "HOTFIX_ISSUE_NOT_FOUND", f"issue {issue_id} nao encontrada"

    issue_status = issues_by_id[issue_id].get("status")

    if issue_status != "open":

        return False, "HOTFIX_ISSUE_NOT_OPEN", f"issue {issue_id} status={issue_status}"



    return True, None, None





def build_hotfix_event(
    current_events: list[dict[str, Any]],
    issue_payload: dict[str, Any],
    *,
    raise_on_invalid: bool = True,
) -> dict[str, Any] | None:
    """M-03 — Constroi hotfix.create event apos validar o request.

    Quando issue_id ou fixes ausentes, devolve None (issue.report comum, sem hotfix).
    Quando validate_hotfix_request falha:
      - raise_on_invalid=True (default): levanta ESAAError(code, message).
      - raise_on_invalid=False: devolve None (compat com callers que tratam None).
    Duplicate hotfix continua retornando None (graceful skip).
    """
    issue_id = issue_payload.get("issue_id")
    fixes = issue_payload.get("fixes")
    if not issue_id or not fixes:
        return None

    # M-03: validacao agora interna; caller nao precisa duplicar.
    ok, code, message = validate_hotfix_request(current_events, issue_payload)
    if not ok:
        if raise_on_invalid:
            raise ESAAError(code or "HOTFIX_INVALID", message or "invalid hotfix request")
        return None

    hotfix_task_id = f"HF-{issue_id}"
    for event in current_events:
        if event["action"] == "hotfix.create" and event["payload"].get("task_id") == hotfix_task_id:
            return None



    seq = next_event_seq(current_events)

    return make_event(

        seq, actor="orchestrator", action="hotfix.create",

        payload={"task_id": hotfix_task_id, "task_kind": "impl",

                 "title": f"Hotfix for {issue_id}",

                 "description": f"Apply a minimal hotfix to resolve issue {issue_id} without regressing immutable done tasks.",

                 "depends_on": [], "targets": [issue_id], "outputs": {"files": [f"src/hotfix/{hotfix_task_id}.txt"]},

                 "is_hotfix": True, "issue_id": issue_id, "fixes": fixes,

                 "scope_patch": issue_payload.get("scope_patch", ["src/hotfix/"]),

                 "required_verification": issue_payload.get("required_verification", ["unit", "regression"]),

                 "baseline_id": issue_payload.get("affected", {}).get("baseline_id", "B-000")}

    )





def build_issue_resolve_event(

    current_events: list[dict[str, Any]],

    task: dict[str, Any],

    review_payload: dict[str, Any],

) -> dict[str, Any] | None:

    if not task.get("is_hotfix"):

        return None

    if review_payload.get("decision") != "approve":

        return None

    issue_id = task.get("issue_id")

    if not issue_id:

        return None

    for event in current_events:

        if event["action"] == "issue.resolve" and event["payload"].get("issue_id") == issue_id:

            return None



    seq = next_event_seq(current_events)

    return make_event(

        seq,

        actor="orchestrator",

        action="issue.resolve",

        payload={

            "issue_id": issue_id,

            "resolution": {

                "status": "resolved_by_hotfix",

                "hotfix_task_id": task["task_id"],

                "review_task_id": review_payload["task_id"],

                "checks": task.get("verification", {}).get("checks", []),

            },

        },

    )





def dumps_pretty(payload: dict[str, Any]) -> str:

    return json.dumps(payload, ensure_ascii=False, indent=2)

