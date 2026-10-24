"""Versioned operator configuration and additive schema activation."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .utils import normalize_rel_path, sha256_hex

PROTOCOL_VERSION = "0.4.2"
DEFAULTS = {
    "timeout_seconds": 60,
    "cpus": 1,
    "memory_mb": 512,
    "pids_limit": 128,
    "log_bytes": 1048576,
    "workspace_mb": 64,
}
BOUNDS = {
    "timeout_seconds": (1, 3600),
    "cpus": (1, 8),
    "memory_mb": (32, 8192),
    "pids_limit": (16, 1024),
    "log_bytes": (1024, 8388608),
    "workspace_mb": (1, 1024),
}


def relative_path(value: str, *, pattern: bool = False) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "invalid relative path")
    value = normalize_rel_path(value)
    parts = value.split("/")
    if (
        value.startswith("/")
        or ":" in value
        or ".." in parts
        or any(p in {".git", ".roadmap"} for p in parts)
    ):
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "protected or external verification path")
    if not pattern and any(c in value for c in "*?["):
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "wildcards not allowed in working directory")
    return value


def normalize_config(raw: Any) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"checks"}
        or not isinstance(raw["checks"], list)
        or not raw["checks"]
    ):
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "config requires a nonempty checks array")
    checks = []
    seen = set()
    for item in raw["checks"]:
        required = {"id", "image", "command", "inputs"}
        if (
            not isinstance(item, dict)
            or not required <= set(item)
            or set(item) - required - {"cwd", *DEFAULTS}
        ):
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "invalid check fields")
        check_id = item["id"]
        if (
            not isinstance(check_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", check_id)
            or check_id in seen
        ):
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "check IDs must be unique identifiers")
        if not isinstance(item["image"], str) or not re.fullmatch(
            r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", item["image"]
        ):
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "image must be pinned by repository@sha256 digest")
        command = item["command"]
        inputs = item["inputs"]
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(x, str) or not x or "\x00" in x for x in command)
        ):
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "command must be a nonempty argument array")
        if not isinstance(inputs, list) or not inputs:
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "inputs must be a nonempty pattern array")
        check = {k: item[k] for k in ("id", "image", "command")}
        check["inputs"] = [relative_path(p, pattern=True) for p in inputs]
        check["cwd"] = relative_path(item.get("cwd", "."))
        for key, default in DEFAULTS.items():
            value = item.get(key, default)
            lo, hi = BOUNDS[key]
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ESAAError("VERIFICATION_CONFIG_INVALID", f"{key} must be an integer in [{lo}, {hi}]")
            check[key] = value
        checks.append(check)
        seen.add(check_id)
    return {"checks": sorted(checks, key=lambda c: c["id"])}


def current_config(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event["action"] == "verification.configure":
            payload = event["payload"]
            config = normalize_config(payload["config"])
            if payload.get("config_sha256") != sha256_hex(config):
                raise ESAAError("VERIFICATION_CONFIG_INVALID", "configuration digest mismatch")
            return {
                "config": config,
                "config_sha256": payload["config_sha256"],
                "event_seq": event["event_seq"],
            }
    raise ESAAError(
        "VERIFICATION_NOT_ENABLED", "run verification enable with an operator-authorized catalog first"
    )


def validate_check_ids(ids: list[str], events: list[dict[str, Any]]) -> list[str]:
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i for i in ids):
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "executable_checks must be a nonempty list of IDs")
    known = {c["id"] for c in current_config(events)["config"]["checks"]}
    if set(ids) - known:
        raise ESAAError("VERIFICATION_CONFIG_INVALID", "task refers to an unknown executable check")
    return sorted(set(ids))


def schema_upgrades(root: Path) -> list[dict[str, str]]:
    """Only add optional properties; preserve custom constraints or refuse conflicts."""
    updates = []
    for filename in ("agent_result.schema.json", "roadmap.schema.json"):
        path = root / ".roadmap" / filename
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ESAAError("VERIFICATION_CONFIG_INVALID", "schema is missing or symlinked")
        schema = json.loads(path.read_text())
        new = copy.deepcopy(schema)
        try:
            if filename.startswith("agent_"):
                properties = new["properties"]["activity_event"]["properties"]["verification"]["properties"]
            else:
                task = new.get("$defs", new.get("definitions", {}))["task"]["properties"]
                wanted = {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                }
                if "executable_checks" in task and task["executable_checks"] != wanted:
                    raise ValueError("custom executable_checks conflicts")
                task["executable_checks"] = wanted
                properties = task["verification"].setdefault("properties", {})
            wanted = {"type": "string", "minLength": 1}
            if "execution_id" in properties and properties["execution_id"] != wanted:
                raise ValueError("custom execution_id conflicts")
            properties["execution_id"] = wanted
        except (KeyError, TypeError, ValueError) as exc:
            raise ESAAError("VERIFICATION_CONFIG_INVALID", f"incompatible schema {filename}: {exc}") from exc
        if new != schema:
            updates.append(
                {
                    "path": ".roadmap/" + filename,
                    "content": json.dumps(new, ensure_ascii=False, indent=2) + "\n",
                }
            )
    return updates


def read_events(root: Path) -> list[dict[str, Any]]:
    from .store import parse_event_store

    if not (root / ".roadmap/activity.jsonl").is_file():
        raise ESAAError("EVENT_STORE_MISSING", "initialize the workspace first")
    return parse_event_store(root)
