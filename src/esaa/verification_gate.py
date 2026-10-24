"""Evidence gates for submit, adapters, and final append under the store lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from .errors import ESAAError
from .file_effects import ARTIFACT_DIR, verify_artifact
from .projector import materialize
from .utils import sha256_hex
from .verification_candidate import matches, prepare_candidate
from .verification_results import find_result


def validate_evidence(
    root: Path, events: list[dict[str, Any]], actor: str, candidate: dict[str, Any]
) -> dict[str, Any] | None:
    activity = candidate.get("activity_event", {})
    if activity.get("action") != "complete":
        return None
    task = next((t for t in materialize(events)[0]["tasks"] if t["task_id"] == activity.get("task_id")), None)
    if task is None or not task.get("executable_checks"):
        return None
    run_id = activity.get("verification", {}).get("execution_id")
    if not isinstance(run_id, str) or not run_id:
        raise ESAAError("VERIFICATION_REQUIRED", "complete requires a passed verification execution_id")
    result = find_result(root, events, run_id)
    if result["status"] != "passed":
        raise ESAAError("VERIFICATION_FAILED", "executable verification did not pass")
    prepared = prepare_candidate(root, events, actor, candidate)
    if (
        result.get("binding_sha256") != sha256_hex(result.get("binding"))
        or result.get("binding_sha256") != prepared["binding_sha256"]
    ):
        raise ESAAError(
            "VERIFICATION_STALE",
            "verification belongs to another candidate, task, inputs, configuration or cycle",
        )
    expected = {c["id"]: c for c in prepared["checks"]}
    results = result["results"]
    if len(results) != len(expected) or {r["id"] for r in results} != set(expected):
        raise ESAAError("VERIFICATION_FAILED", "required check coverage is incomplete")
    for check in results:
        if (
            check.get("status") != "passed"
            or type(check.get("exit_code")) is not int
            or check["exit_code"] != 0
            or check.get("image") != expected[check["id"]]["image"]
        ):
            raise ESAAError(
                "VERIFICATION_FAILED", "required executable check is not a successful authorized image"
            )
    return prepared


def _artifact_updates(root: Path, writes: list[dict[str, Any]]) -> list[dict[str, str]]:
    updates = []
    for write in writes:
        for effect in write["payload"].get("effects", []):
            relative = effect.get("artifact_path", "")
            path = root / relative
            if (
                not relative
                or path.is_symlink()
                or not path.resolve().is_relative_to((root / ARTIFACT_DIR).resolve())
            ):
                raise ESAAError("VERIFICATION_FAILED", "invalid candidate artifact path")
            ok, _ = verify_artifact(root, relative)
            if not ok:
                raise ESAAError("VERIFICATION_FAILED", "candidate artifact integrity failure")
            data = json.loads(path.read_text())
            content = data["content"]
            if (
                data["artifact_sha256"] != effect["artifact_sha256"]
                or hashlib.sha256(content.encode()).hexdigest() != effect["after_sha256"]
            ):
                raise ESAAError("VERIFICATION_FAILED", "candidate content does not match file effect")
            updates.append({"path": effect["path"], "content": content})
    return updates


def validate_pending(root: Path, events: list[dict[str, Any]], pending: list[dict[str, Any]]) -> None:
    """Reconstruct normalized deliveries, including adapter batches, before append."""
    if not any(e["action"] == "complete" for e in pending):
        return
    prefix = list(events)
    writes = [e for e in pending if e["action"] == "orchestrator.file.write"]
    for event in pending:
        if event["action"] == "complete":
            task_id = event["payload"]["task_id"]
            task = next((t for t in materialize(prefix)[0]["tasks"] if t["task_id"] == task_id), None)
            if task and task.get("executable_checks"):
                own = [w for w in writes if w["payload"].get("task_id") == task_id]
                candidate = {"activity_event": event["payload"], "file_updates": _artifact_updates(root, own)}
                prepared = cast(dict[str, Any], validate_evidence(root, prefix, event["actor"], candidate))
                patterns = [p for c in prepared["checks"] for p in c["inputs"]]
                if any(
                    matches(p, patterns)
                    for w in writes
                    if w not in own
                    for p in w["payload"].get("files", [])
                ):
                    raise ESAAError(
                        "VERIFICATION_STALE", "another delivery in the batch modifies verification inputs"
                    )
        prefix.append(event)
