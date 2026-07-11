from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .errors import ESAAError
from .events import make_event
from .file_effects import commit_staged, discard_staged
from .projector import materialize
from .project_profile import project_profile_view
from .runtime_policy import (
    attempt_expired,
    is_blocked_by_max_attempts,
    is_in_cooldown,
    parse_duration,
)
from .seeds import (
    all_tasks_done,
    build_dispatch_context,
    list_eligible_tasks,
    parallel_groups,
    select_task_wave,
    tasks_with_planned_plugins,
)
from .store import load_agent_contract, load_agent_result_schema, next_event_seq, parse_event_store


class ExecutionMixin:
    def eligible(self) -> dict[str, Any]:

        events = parse_event_store(self.root)

        roadmap, _, _ = materialize(events)

        tasks, task_sources = tasks_with_planned_plugins(self.root, roadmap["tasks"])
        suppressed_superseded = [
            {"task_id": task["task_id"], "title": task.get("title")}
            for task in tasks
            if task.get("status") == "todo" and task.get("superseded_by")
        ]

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
                {
                    "task_id": t["task_id"],
                    "task_kind": t["task_kind"],
                    "title": t["title"],
                    "outputs": t.get("outputs", {}).get("files", []),
                    "depends_on": t.get("depends_on", []),
                    "source": task_sources.get(t["task_id"], "event_store"),
                }
                for t in elig
            ],
            "parallel_groups": groups,
            "suppressed_superseded_count": len(suppressed_superseded),
            "suppressed_superseded": suppressed_superseded[:20],
        }

    def run(self, steps: int | None = 1, dry_run: bool = False, parallel: int = 1) -> dict[str, Any]:

        if steps is not None and steps < 1:

            raise ESAAError("INVALID_ARGUMENT", "steps must be >= 1")

        if parallel < 1:

            raise ESAAError("INVALID_ARGUMENT", "parallel must be >= 1")

        events = parse_event_store(self.root)

        contract = load_agent_contract(self.root)

        schema = load_agent_result_schema(self.root)
        project_profile = project_profile_view(events)

        policy = self._policy()

        max_attempts = policy.get("attempt_limits", {}).get("max_attempts_per_task", 3)

        cooldown = parse_duration(policy.get("attempt_limits", {}).get("cooldown_between_attempts", "PT2M"))

        ttl = parse_duration(policy.get("attempt_lifecycle", {}).get("ttl", "PT30M"))

        new_events: list[dict[str, Any]] = []
        staged_file_effects: list[dict[str, Any]] = []
        # M1: write-set com escopo do run() inteiro - staging so commita no fim,
        # entao conflito entre iteracoes precisa ser detectado aqui, nao por wave.
        run_write_set: list[str] = []
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

            candidates = [
                t
                for t in effective_roadmap["tasks"]
                if not is_blocked_by_max_attempts(events + new_events, t["task_id"], max_attempts)
                and not is_in_cooldown(events + new_events, t["task_id"], now, cooldown)
            ]

            wave = select_task_wave(candidates, limit=parallel)

            if not wave:

                break

            # R2: TTL expirado em in_progress -> output.rejected (ATTEMPT_TIMEOUT)

            runnable_wave: list[dict[str, Any]] = []

            for task in wave:

                if task["status"] == "in_progress" and attempt_expired(
                    events + new_events, task["task_id"], now, ttl
                ):

                    seq_to = next_event_seq(events + new_events)

                    timeout_ev = make_event(
                        seq_to,
                        actor="orchestrator",
                        action="output.rejected",
                        payload={
                            "task_id": task["task_id"],
                            "error_code": "ATTEMPT_TIMEOUT",
                            "message": f"attempt exceeded ttl {ttl}",
                            "source_action": "claim",
                        },
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

            contexts = [
                (
                    task,
                    build_dispatch_context(
                        effective_roadmap,
                        task,
                        contract,
                        schema=schema,
                        project_profile=project_profile,
                    ),
                )
                for task in runnable_wave
            ]

            def execute_context(
                item: tuple[dict[str, Any], dict[str, Any]],
            ) -> tuple[dict[str, Any], dict[str, Any] | None, Exception | None]:

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

            for task, output, execute_error in outputs:

                current_seq = next_event_seq(events + new_events)

                executed += 1

                try:

                    if execute_error is not None:

                        if isinstance(execute_error, ESAAError):

                            raise execute_error

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
                        wave_write_set=run_write_set,
                        staged_file_effects=staged_file_effects,
                    )
                except ESAAError as exc:

                    rejected += 1

                    reject_event = make_event(
                        current_seq,
                        actor="orchestrator",
                        action="output.rejected",
                        payload={
                            "task_id": task["task_id"],
                            "error_code": exc.code,
                            "message": exc.message,
                            "source_action": (
                                output.get("activity_event", {}).get("action", "unknown")
                                if isinstance(output, dict)
                                else "unknown"
                            ),
                        },
                    )

                    new_events.append(reject_event)

                    # R2: se atingiu max_attempts, escalar via issue.report severity=high

                    if is_blocked_by_max_attempts(events + new_events, task["task_id"], max_attempts):

                        esc_seq = next_event_seq(events + new_events)

                        esc = make_event(
                            esc_seq,
                            actor="orchestrator",
                            action="issue.report",
                            payload={
                                "task_id": task["task_id"],
                                "issue_id": f"ISS-MAXATT-{task['task_id']}",
                                "severity": "high",
                                "title": "Max attempts reached",
                                "evidence": {
                                    "symptom": f"{max_attempts} penalizing rejections",
                                    "repro_steps": [f"task {task['task_id']}", "see output.rejected events"],
                                },
                            },
                        )

                        new_events.append(esc)

                except ValueError as exc:

                    rejected += 1

                    reject_event = make_event(
                        current_seq,
                        actor="orchestrator",
                        action="output.rejected",
                        payload={
                            "task_id": task["task_id"],
                            "error_code": "LLM_PARSE_FAILED",
                            "message": str(exc),
                            "source_action": "unknown",
                        },
                    )

                    new_events.append(reject_event)

        final_events = events + new_events

        final_roadmap, final_issues, final_lessons = materialize(final_events)

        if all_tasks_done(final_roadmap["tasks"]) and final_roadmap["meta"]["run"]["status"] != "success":

            run_end = make_event(
                next_event_seq(final_events),
                actor="orchestrator",
                action="run.end",
                payload={"status": "success"},
            )

            final_events.append(run_end)

            new_events.append(run_end)

            final_roadmap, final_issues, final_lessons = materialize(final_events)

        verify_start = make_event(
            next_event_seq(final_events),
            actor="orchestrator",
            action="verify.start",
            payload={"strict": True},
        )

        final_events.append(verify_start)

        new_events.append(verify_start)

        final_roadmap, final_issues, final_lessons = materialize(final_events)

        verify_ok = make_event(
            next_event_seq(final_events),
            actor="orchestrator",
            action="verify.ok",
            payload={"projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"]},
        )

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

        result = {
            "status": "dry_run" if dry_run else "accepted",
            "steps_requested": steps,
            "steps_executed": executed,
            "events_appended": len(new_events),
            "rejected": rejected,
            "blocked_by_attempt_lifecycle": blocked,
            "files_written": files_written,
            "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],
            "verify_status": final_roadmap["meta"]["run"]["verify_status"],
            "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"],
        }
        if dry_run:
            result["would_append_events"] = len(new_events)
            result["simulated_last_event_seq"] = result["last_event_seq"]
            result["simulated_projection_hash_sha256"] = result["projection_hash_sha256"]
        return result
