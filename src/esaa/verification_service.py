"""Operator commands for optional executable verification."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from .errors import ESAAError
from .events import make_event
from .file_effects import commit_staged, discard_staged, stage_and_compute
from .store import next_event_seq
from .utils import sha256_hex
from .verification_config import (
    PROTOCOL_VERSION,
    current_config,
    normalize_config,
    read_events,
    schema_upgrades,
)

if TYPE_CHECKING:
    from pathlib import Path


class VerificationMixin:
    if TYPE_CHECKING:
        root: Path

        def _commit_orchestrator_events(
            self,
            candidate_events: list[dict[str, Any]],
            dry_run: bool = False,
            precommit: Any = None,
            postcommit: Any = None,
        ) -> dict[str, Any]: ...

    def verification_enable(self, config: Any, dry_run: bool = False) -> dict[str, Any]:
        normalized = normalize_config(config)
        events = read_events(self.root)
        updates = schema_upgrades(self.root)
        before = {
            item["path"]: hashlib.sha256((self.root / item["path"]).read_bytes()).hexdigest()
            for item in updates
        }

        def guard(_events):
            for path, digest in before.items():
                target = self.root / path
                if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ESAAError("VERIFICATION_STALE", "schema changed during activation")

        event = make_event(
            next_event_seq(events),
            "orchestrator",
            "verification.configure",
            {
                "config": normalized,
                "config_sha256": sha256_hex(normalized),
                "protocol_version": PROTOCOL_VERSION,
            },
        )
        event["schema_version"] = PROTOCOL_VERSION
        staged: list[dict[str, Any]] = []
        try:
            candidates = [event]
            if updates and not dry_run:
                staged, effects = stage_and_compute(self.root, updates)
                candidates.append(
                    make_event(
                        next_event_seq(events) + 1,
                        "orchestrator",
                        "orchestrator.file.write",
                        {
                            "task_id": "verification.configure",
                            "files": [u["path"] for u in updates],
                            "effects": effects,
                        },
                    )
                )
            result = self._commit_orchestrator_events(
                candidates,
                dry_run=dry_run,
                precommit=guard,
                postcommit=lambda: commit_staged(self.root, staged),
            )
            return {
                **result,
                "config_sha256": sha256_hex(normalized),
                "schema_updates": [u["path"] for u in updates],
                "protocol_version": PROTOCOL_VERSION,
            }
        except BaseException:
            discard_staged(staged)
            raise

    def verification_show(self) -> dict[str, Any]:
        return current_config(read_events(self.root))

    def verification_run(
        self, task_id: str, candidate: Any, actor: str, dry_run: bool = False
    ) -> dict[str, Any]:
        from uuid import uuid4

        from .verification_candidate import matches, prepare_candidate
        from .verification_executor import execute_check
        from .verification_results import result_digest, save_logs

        events = read_events(self.root)
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("activity_event"), dict)
            or candidate["activity_event"].get("task_id") != task_id
        ):
            raise ESAAError("SCHEMA_INVALID", "candidate task does not match requested task")
        prepared = prepare_candidate(self.root, events, actor, candidate)
        if dry_run:
            return {
                "status": "dry_run",
                "binding": prepared["binding"],
                "binding_sha256": prepared["binding_sha256"],
                "checks": prepared["checks"],
                "would_execute": False,
            }
        results = []
        for check in prepared["checks"]:
            files = {p: data for p, data in prepared["files"].items() if matches(p, check["inputs"])}
            results.append(execute_check(check, files))
            if results[-1]["status"] == "cancelled":
                break
        run_id = uuid4().hex
        payload = {
            "run_id": run_id,
            "task_id": task_id,
            "actor": actor,
            "binding": prepared["binding"],
            "binding_sha256": prepared["binding_sha256"],
            "status": (
                "cancelled"
                if any(r["status"] == "cancelled" for r in results)
                else "passed"
                if len(results) == len(prepared["checks"]) and all(r["status"] == "passed" for r in results)
                else "failed"
            ),
            "results": results,
        }
        save_logs(self.root, run_id, results)

        def guard(current):
            try:
                now = prepare_candidate(self.root, current, actor, candidate)
                if now["binding_sha256"] != prepared["binding_sha256"]:
                    payload["status"] = "stale"
            except ESAAError:
                payload["status"] = "stale"
            payload["result_sha256"] = result_digest(payload)

        guard(events)
        event = make_event(next_event_seq(events), "orchestrator", "verification.run", payload)
        event["schema_version"] = PROTOCOL_VERSION
        self._commit_orchestrator_events([event], precommit=guard)
        return payload

    def verification_result(self, run_id: str) -> dict[str, Any]:
        from .verification_results import find_result

        return find_result(self.root, read_events(self.root), run_id)
