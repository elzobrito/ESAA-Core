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
from .project_profile import project_profile_view
from .projection_check import REBUILD_HINT, compare_projections
from .projector import finalize_views, materialize
from .runner_metrics import normalize_runner_metrics
from .runtime_policy import load_policy, parse_duration
from .seeds import BASELINE_LESSONS, load_plugin_seeds, seed_tasks
from .snapshot import load_verified_replay
from .store_runtime import (
    append_events,
    append_transactional,
    ensure_event_store,
    load_project_profile,
    next_event_seq,
    parse_event_store,
    record_concurrency_metric,
    save_issues,
    save_lessons,
    save_project_profile,
    save_roadmap,
)
from .verify_annotations import chain_status, verify_annotations


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
        self,
        run_id: str = "RUN-0001",
        master_correlation_id: str = "CID-ESAA-INIT",
        force: bool = False,
        with_demo_tasks: bool = False,
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

        roadmap_preview, _, _ = materialize(events)
        if events:
            from .constants import PROJECTOR_VERSION

            events[-1]["projection_hash_after"] = roadmap_preview["meta"]["run"]["projection_hash_sha256"]
            events[-1]["projector_version"] = PROJECTOR_VERSION

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
        replay = load_verified_replay(self.root)
        roadmap, issues, lessons = finalize_views(replay.state)
        if replay.used_snapshot:
            profile_events = [e for e in replay.tail_events if e["action"] == "project.profile.set"]
            project_profile = (
                project_profile_view(profile_events) if profile_events else replay.project_profile
            )
        else:
            project_profile = replay.project_profile

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
        return self._verify_impl(full=False)

    def verify_full(self) -> dict[str, Any]:
        return self._verify_impl(full=True)

    def _verify_impl(self, *, full: bool = False) -> dict[str, Any]:
        try:
            replay = load_verified_replay(self.root, full=full)
            projected, issues_view, lessons_view = finalize_views(replay.state, copy=False)
            if replay.used_snapshot:
                profile_events = [e for e in replay.tail_events if e["action"] == "project.profile.set"]
                projected_profile = (
                    project_profile_view(profile_events) if profile_events else replay.project_profile
                )
                events = (
                    parse_event_store(self.root)
                    if replay.has_actor_events
                    or any(e["action"].startswith("actor.") for e in replay.tail_events)
                    else replay.effective_events
                )
            else:
                events = replay.full_events or []
                projected_profile = replay.project_profile
        except CorruptedStoreError as exc:
            return {
                "verify_status": "corrupted",
                "error_code": exc.code,
                "error_message": exc.message,
                "last_event_seq": None,
                "projection_hash_sha256": None,
            }
        computed_hash = projected["meta"]["run"]["projection_hash_sha256"]
        computed_seq = projected["meta"]["run"]["last_event_seq"]
        from .trust_root import catch_up_checkpoint

        caught = catch_up_checkpoint(self.root, events, computed_hash)
        if caught:
            return caught
        # AUD-O0-060 (GOV-05): compara o conteudo das projecoes, nao so o hash declarado.
        views = {"roadmap.json": projected, "issues.json": issues_view, "lessons.json": lessons_view}
        check = compare_projections(self.root, views, ignore_updated_at=computed_seq == 0)
        if check["problems"].get("roadmap.json") == "missing":
            return {
                "verify_status": "mismatch",
                "reason": "roadmap_missing",
                "last_event_seq": computed_seq,
                "projection_hash_sha256": computed_hash,
            }
        stored_run = ((check["stored_roadmap"] or {}).get("meta") or {}).get("run") or {}
        stored_hash, stored_seq = stored_run.get("projection_hash_sha256"), stored_run.get("last_event_seq")
        try:
            profile_matches = projected_profile == load_project_profile(self.root)
        except (ValueError, OSError):
            profile_matches = False
        if (
            computed_hash == stored_hash
            and computed_seq == stored_seq
            and profile_matches
            and not check["divergent"]
        ):
            annotations = verify_annotations(events, projected.get("tasks", []))
            if replay.used_snapshot and replay.prefix_chain_status == "ok":
                annotations["chain_status"] = "ok"
            if replay.used_snapshot and replay.prefix_ts_regression is not None:
                warnings = list(annotations.get("warnings", []))
                if not any(w.get("code") == replay.prefix_ts_regression.get("code") for w in warnings):
                    warnings.append(replay.prefix_ts_regression)
                annotations["warnings"] = warnings
            return {
                "verify_status": "ok",
                "last_event_seq": computed_seq,
                "projection_hash_sha256": computed_hash,
                "project_profile": projected_profile is not None,
                "hash_checked": replay.state.get("_hash_checked", 0),
                "hash_unchecked": replay.state.get("_hash_unchecked", 0),
                **annotations,
            }
        return {
            "verify_status": "mismatch",
            "last_event_seq": computed_seq,
            "projection_hash_sha256": computed_hash,
            "stored_last_event_seq": stored_seq,
            "stored_projection_hash_sha256": stored_hash,
            "project_profile_mismatch": not profile_matches,
            "divergent": check["divergent"],
            "chain_status": chain_status(events),
            **({"unreadable": check["problems"]} if check["problems"] else {}),
            "hint": REBUILD_HINT,
        }

    def metrics(self) -> dict[str, Any]:
        return compute_metrics(parse_event_store(self.root))

    def recover_file_effects(self, dry_run: bool = False) -> dict[str, Any]:
        return recover_file_effects_from_events(self.root, parse_event_store(self.root), dry_run=dry_run)

    def _append_events_transactionally(
        self,
        base_events: list[dict[str, Any]],
        new_events: list[dict[str, Any]],
        precommit=None,
        postcommit=None,
        base_hash: str | None = None,
        result_task_id: str | None = None,
        planned_effects: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        expected_first_seq = next_event_seq(base_events)
        # AUD-O1-010: quem ja reproduziu base_events informa o hash e evita outro replay.
        expected_hash = base_hash or _projection_hash(base_events)
        concurrency = _concurrency_policy(self._policy())
        max_retries = int(concurrency["submit_retries"])
        retry_backoff = float(concurrency["retry_backoff"])
        lock_max_age = float(concurrency["lock_max_age"])

        def build_events(current_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if precommit is not None:
                precommit(current_events)
            current_first_seq = next_event_seq(current_events)
            adjusted: list[dict[str, Any]] = []
            for offset, event in enumerate(new_events):
                expected_seq = current_first_seq + offset
                adjusted_event = dict(event)
                adjusted_event["event_seq"] = expected_seq
                adjusted_event["event_id"] = f"EV-{expected_seq:08d}"
                adjusted.append(adjusted_event)
            if attempt:
                from .orchestrator_commit import refresh_verification_hashes

                refresh_verification_hashes(current_events, adjusted)
            if planned_effects is not None and any(e["action"] == "complete" for e in adjusted):
                from .file_effects import ARTIFACT_DIR, persist_artifact

                plans = planned_effects if isinstance(planned_effects, list) else [planned_effects]
                for plan in plans:
                    if not plan:
                        continue
                    for art in plan.get("artifacts", []):
                        art_path = self.root / ARTIFACT_DIR / f"{art['artifact_sha256']}.json"
                        if not art_path.exists():
                            persist_artifact(self.root, art)
                            created_artifacts.append(art_path)
            from .verification_gate import validate_pending

            validate_pending(self.root, current_events, adjusted)
            return adjusted

        attempt = 0
        while True:
            created_artifacts: list[Path] = []
            postcommit_entered = False

            def _wrapped_postcommit() -> None:
                nonlocal postcommit_entered
                postcommit_entered = True
                if postcommit is not None:
                    postcommit()

            try:
                return append_transactional(
                    self.root,
                    build_events,
                    expected_first_seq=expected_first_seq if attempt == 0 else None,
                    expected_projection_hash=expected_hash if attempt == 0 else None,
                    lock_max_age=lock_max_age,
                    after_append=(
                        _wrapped_postcommit
                        if (postcommit is not None or planned_effects is not None)
                        else None
                    ),
                    result_task_id=result_task_id,
                )
            except ESAAError as exc:
                if not postcommit_entered:
                    for art_path in created_artifacts:
                        art_path.unlink(missing_ok=True)
                if exc.code not in {"STALE_STATE_SEQ", "STALE_STATE_HASH"} or attempt >= max_retries:
                    raise
                if exc.code not in {"STALE_STATE_SEQ", "STALE_STATE_HASH"} or attempt >= max_retries:
                    raise
                record_concurrency_metric("stale_conflicts")
                record_concurrency_metric("submit_retries")
                sleep_for = retry_backoff * (2**attempt) * random.uniform(0.5, 1.5)
                attempt += 1
            except BaseException:
                if not postcommit_entered:
                    for art_path in created_artifacts:
                        art_path.unlink(missing_ok=True)
                raise
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
        self, candidate_events: list[dict[str, Any]], dry_run: bool = False, precommit=None, postcommit=None
    ) -> dict[str, Any]:

        from .orchestrator_commit import commit_orchestrator_events

        return commit_orchestrator_events(
            self.root,
            candidate_events,
            append_transactional,
            dry_run=dry_run,
            precommit=precommit,
            postcommit=postcommit,
            lock_max_age=float(_concurrency_policy(self._policy())["lock_max_age"]),
        )

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
