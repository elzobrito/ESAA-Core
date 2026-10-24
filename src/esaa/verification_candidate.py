"""Normalize a delivery and snapshot only operator-authorized inputs."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .projector import materialize
from .runtime_policy import load_policy
from .store import load_agent_contract, load_agent_result_schema, require_task
from .utils import sha256_hex
from .validator import validate_agent_output, validate_file_update_resource_limits
from .verification_config import current_config, relative_path, validate_check_ids


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def cycle_id(events: list[dict[str, Any]], task_id: str) -> int:
    return max(
        (
            e["event_seq"]
            for e in events
            if e["payload"].get("task_id") == task_id
            and (
                e["action"] == "claim"
                or (e["action"] == "review" and e["payload"].get("decision") == "request_changes")
            )
        ),
        default=0,
    )


def safe_target(root: Path, rel: str) -> Path:
    relative_path(rel)
    target = root / rel
    for part in (target, *target.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "symlinks are not executable-check inputs")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "input escapes workspace")
    return target


def prepare_candidate(
    root: Path, events: list[dict[str, Any]], actor: str, candidate: dict[str, Any]
) -> dict[str, Any]:
    from .submission import _normalize_file_updates

    if not isinstance(candidate, dict) or not isinstance(candidate.get("activity_event"), dict):
        raise ESAAError("SCHEMA_INVALID", "candidate must be a complete envelope")
    activity = candidate["activity_event"]
    if activity.get("action") != "complete":
        raise ESAAError("SCHEMA_INVALID", "verification candidate must use complete")
    task = require_task(materialize(events)[0], activity.get("task_id"))
    if task["status"] != "in_progress" or task.get("assigned_to") != actor:
        raise ESAAError("LOCK_VIOLATION", "verification requires the in-progress claim owner")
    conf = current_config(events)
    ids = validate_check_ids(task.get("executable_checks", []), events)
    checks = [c for c in conf["config"]["checks"] if c["id"] in ids]
    event, updates = validate_agent_output(
        candidate, load_agent_result_schema(root), load_agent_contract(root), task
    )
    if any(u["path"].startswith("runtime://") for u in updates):
        raise ESAAError(
            "VERIFICATION_CONFIG_INVALID", "external file effects are unsupported for executable checks"
        )
    updates = _normalize_file_updates(root, updates)
    validate_file_update_resource_limits(updates, load_policy(root))
    patterns = [p for c in checks for p in c["inputs"]]
    files: dict[str, bytes] = {}
    source_manifest = {}
    total = 0
    limit = min(c["workspace_mb"] for c in checks) * 1024 * 1024
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".git", ".roadmap", "__pycache__", ".pytest_cache"}]
        for name in dirs:
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink() and (matches(rel, patterns) or matches(rel + "/__probe__", patterns)):
                raise ESAAError("VERIFICATION_CONFIG_INVALID", "symlink directory in verification inputs")
        for name in names:
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if not matches(rel, patterns):
                continue
            p = safe_target(root, rel)
            if not p.is_file():
                raise ESAAError("VERIFICATION_CONFIG_INVALID", "input is not a regular file")
            if total + p.stat().st_size > limit or len(files) >= 10000:
                raise ESAAError("RESOURCE_LIMIT_EXCEEDED", "verification snapshot is too large")
            data = p.read_bytes()
            total += len(data)
            files[rel] = data
            source_manifest[rel] = hashlib.sha256(data).hexdigest()
    for update in updates:
        rel = update["path"]
        safe_target(root, rel)
        if not matches(rel, patterns):
            raise ESAAError(
                "VERIFICATION_CONFIG_INVALID", "candidate file is outside configured check inputs"
            )
        files[rel] = update["content"].encode("utf-8")
    if sum(len(data) for data in files.values()) > limit:
        raise ESAAError("RESOURCE_LIMIT_EXCEEDED", "candidate snapshot is too large")
    semantic = {k: event[k] for k in ("action", "task_id", "prior_status", "issue_id", "fixes") if k in event}
    binding = {
        "task_id": task["task_id"],
        "actor": actor,
        "cycle": cycle_id(events, task["task_id"]),
        "config_sha256": conf["config_sha256"],
        "config_event_seq": conf["event_seq"],
        "checks": ids,
        "input_manifest": source_manifest,
        "candidate_sha256": sha256_hex(
            {"event": semantic, "updates": sorted(updates, key=lambda u: u["path"])}
        ),
    }
    return {
        "binding": binding,
        "binding_sha256": sha256_hex(binding),
        "checks": checks,
        "files": files,
        "task": task,
    }
