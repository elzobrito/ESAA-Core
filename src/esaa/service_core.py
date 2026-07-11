from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .adapters import AgentAdapter, MockAgentAdapter
from .errors import CorruptedStoreError, ESAAError
from .events import make_event
from .file_effects import recover_file_effects as recover_file_effects_from_events
from .metrics import compute_metrics
from .projector import materialize
from .project_profile import project_profile_view
from .runner_metrics import normalize_runner_metrics
from .runtime_policy import load_policy, parse_duration
from .seeds import BASELINE_LESSONS, all_tasks_done, load_plugin_seeds, seed_tasks
from .store import (
    append_events,
    append_transactional,
    ensure_event_store,
    load_roadmap,
    load_project_profile,
    next_event_seq,
    parse_event_store,
    record_concurrency_metric,
    save_issues,
    save_lessons,
    save_project_profile,
    save_roadmap,
)


def _projection_hash(events: list[dict[str, Any]]) -> str:
    roadmap, _, _ = materialize(events)
    return roadmap["meta"]["run"]["projection_hash_sha256"]


def _duration_seconds(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    parsed = parse_duration(str(value)).total_seconds()
    return parsed if parsed > 0 else default


def _concurrency_policy(policy: dict[str, Any]) -> dict[str, float | int]:
    data = policy.get("concurrency", {}) if isinstance(policy.get("concurrency", {}), dict) else {}
    return {
        "submit_retries": int(data.get("submit_retries", 2)),
        "retry_backoff": _duration_seconds(data.get("retry_backoff"), 0.2),
        "lock_max_age": _duration_seconds(data.get("lock_max_age"), 120.0),
    }


class ESAAServiceCore:
    def __init__(self, root: Path, adapter: AgentAdapter | None = None) -> None:

        self.root = root

        self.adapter = adapter or MockAgentAdapter()

        self._policy_cache: dict[str, Any] | None = None

    def _policy(self) -> dict[str, Any]:

        if self._policy_cache is None:

            self._policy_cache = load_policy(self.root)

        return self._policy_cache

    def init(
        self, run_id: str = "RUN-0001", master_correlation_id: str = "CID-ESAA-INIT",
        force: bool = False, with_demo_tasks: bool = False,
    ) -> dict[str, Any]:

        roadmap_dir = self.root / ".roadmap"

        roadmap_dir.mkdir(parents=True, exist_ok=True)

        if not force and (self.root / ".roadmap/activity.jsonl").exists():

            existing = (self.root / ".roadmap/activity.jsonl").read_text(encoding="utf-8").strip()

            if existing:

                raise ESAAError(
                    "INIT_BLOCKED", "event store already contains events; use --force to reinitialize"
                )

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

        elif with_demo_tasks:
            tasks = seed_tasks()
        else:
            tasks = []

        events: list[dict[str, Any]] = []

        seq = 1

        events.append(make_event(seq, actor="orchestrator", action="run.start", payload=run_start_payload))

        seq += 1

        for task in tasks:

            events.append(make_event(seq, actor="orchestrator", action="task.create", payload=task))

            seq += 1

        # FIX-1813: baseline lessons reseed - emite orchestrator.view.mutate com lessons

        # canonicas. O projetor reconstroi lessons.json a partir deste evento (R1-fix).

        events.append(
            make_event(
                seq,
                actor="orchestrator",
                action="orchestrator.view.mutate",
                payload={
                    "target": "lessons",
                    "change": "baseline_reseed",
                    "lessons": BASELINE_LESSONS,
                },
            )
        )

        seq += 1

        events.append(make_event(seq, actor="orchestrator", action="verify.start", payload={"strict": True}))

        seq += 1

        roadmap_preview, _, _ = materialize(events)

        events.append(
            make_event(
                seq,
                actor="orchestrator",
                action="verify.ok",
                payload={"projection_hash_sha256": roadmap_preview["meta"]["run"]["projection_hash_sha256"]},
            )
        )

        path = ensure_event_store(self.root)

        path.write_text("", encoding="utf-8")

        append_events(self.root, events)

        roadmap, issues, lessons = materialize(events)
        project_profile = project_profile_view(events)

        save_roadmap(self.root, roadmap)

        save_issues(self.root, issues)

        save_lessons(self.root, lessons)
        save_project_profile(self.root, project_profile)

        return {
            "run_id": run_id,
            "events_written": len(events),
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
            "with_demo_tasks": with_demo_tasks,
            "tasks_seeded": [task["task_id"] for task in tasks],
            "task_source": "plugin" if seed else ("demo" if with_demo_tasks else "empty"),
        }

    def project(self) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, issues, lessons = materialize(events)
        project_profile = project_profile_view(events)

        save_roadmap(self.root, roadmap)

        save_issues(self.root, issues)

        save_lessons(self.root, lessons)
        save_project_profile(self.root, project_profile)

        return {
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
            "tasks": len(roadmap["tasks"]),
            "issues": len(issues["issues"]),
            "lessons": len(lessons["lessons"]),
            "project_profile": project_profile is not None,
        }

    def verify(self) -> dict[str, Any]:

        try:

            events = parse_event_store(self.root)

            projected, _, _ = materialize(events)
            projected_profile = project_profile_view(events)

        except CorruptedStoreError as exc:

            return {
                "verify_status": "corrupted",
                "error_code": exc.code,
                "error_message": exc.message,
                "last_event_seq": None,
                "projection_hash_sha256": None,
            }

        stored = load_roadmap(self.root)

        if stored is None:

            return {
                "verify_status": "mismatch",
                "reason": "roadmap_missing",
                "last_event_seq": projected["meta"]["run"]["last_event_seq"],
                "projection_hash_sha256": projected["meta"]["run"]["projection_hash_sha256"],
            }

        computed_hash = projected["meta"]["run"]["projection_hash_sha256"]

        stored_hash = stored.get("meta", {}).get("run", {}).get("projection_hash_sha256")

        computed_seq = projected["meta"]["run"]["last_event_seq"]

        stored_seq = stored.get("meta", {}).get("run", {}).get("last_event_seq")

        stored_profile = load_project_profile(self.root)
        profile_matches = projected_profile == stored_profile

        if computed_hash == stored_hash and computed_seq == stored_seq and profile_matches:

            return {
                "verify_status": "ok",
                "last_event_seq": computed_seq,
                "projection_hash_sha256": computed_hash,
                "project_profile": projected_profile is not None,
            }

        return {
            "verify_status": "mismatch",
            "last_event_seq": computed_seq,
            "projection_hash_sha256": computed_hash,
            "stored_last_event_seq": stored_seq,
            "stored_projection_hash_sha256": stored_hash,
            "project_profile_mismatch": not profile_matches,
        }

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
        concurrency = _concurrency_policy(self._policy())
        max_retries = int(concurrency["submit_retries"])
        retry_backoff = float(concurrency["retry_backoff"])
        lock_max_age = float(concurrency["lock_max_age"])

        def build_events(current_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            current_first_seq = next_event_seq(current_events)
            adjusted: list[dict[str, Any]] = []
            for offset, event in enumerate(new_events):
                expected_seq = current_first_seq + offset
                adjusted_event = dict(event)
                adjusted_event["event_seq"] = expected_seq
                adjusted_event["event_id"] = f"EV-{expected_seq:08d}"
                adjusted.append(adjusted_event)
            return adjusted

        attempt = 0
        while True:
            try:
                return append_transactional(
                    self.root,
                    build_events,
                    expected_first_seq=expected_first_seq if attempt == 0 else None,
                    expected_projection_hash=expected_hash if attempt == 0 else None,
                    lock_max_age=lock_max_age,
                )
            except ESAAError as exc:
                if exc.code not in {"STALE_STATE_SEQ", "STALE_STATE_HASH"} or attempt >= max_retries:
                    raise
                record_concurrency_metric("stale_conflicts")
                record_concurrency_metric("submit_retries")
                sleep_for = retry_backoff * (2**attempt) * random.uniform(0.5, 1.5)
                attempt += 1
                if sleep_for > 0:
                    time.sleep(sleep_for)

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

    def _commit_orchestrator_events(
        self, candidate_events: list[dict[str, Any]], dry_run: bool = False
    ) -> dict[str, Any]:

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

            run_end = make_event(
                next_event_seq(all_events),
                actor="orchestrator",
                action="run.end",
                payload={"status": "success"},
            )

            all_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(all_events)

        verify_start = make_event(
            next_event_seq(all_events), actor="orchestrator", action="verify.start", payload={"strict": True}
        )

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
        project_profile = project_profile_view(selected)

        if write_views:

            save_roadmap(self.root, roadmap)

            save_issues(self.root, issues)

            save_lessons(self.root, lessons)
            save_project_profile(self.root, project_profile)

        return {
            "events_replayed": len(selected),
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
            "verify_status": "ok",
        }
