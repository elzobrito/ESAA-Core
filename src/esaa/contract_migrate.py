"""Selective, idempotent migration of active agent and roadmap schemas.

This updates only the packaged schema files required for binary file_updates
and per-task resource_limits. Event stores, projections, policies and local
contracts stay untouched. bootstrap --force is not a substitute.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .errors import ESAAError

MIGRATABLE_SCHEMAS = ("agent_result.schema.json", "roadmap.schema.json")
PROTECTED_RELATIVE_PATHS = (
    ".roadmap/activity.jsonl",
    ".roadmap/roadmap.json",
    ".roadmap/issues.json",
    ".roadmap/lessons.json",
    ".roadmap/project_profile.json",
)


def _packaged_schema(name: str) -> dict[str, Any]:
    raw = resources.files("esaa").joinpath("templates", name).read_text(encoding="utf-8")
    return json.loads(raw)


def _packaged_binary_arm() -> dict[str, Any]:
    template = _packaged_schema("agent_result.schema.json")
    for arm in template["properties"]["file_updates"]["items"]["oneOf"]:
        if isinstance(arm, dict) and "binary" in arm.get("required", []):
            return copy.deepcopy(arm)
    raise ESAAError("CONTRACT_MIGRATE_INVALID", "packaged agent_result schema lacks binary variant")


def _packaged_resource_limits() -> dict[str, Any]:
    template = _packaged_schema("roadmap.schema.json")
    task = template.get("$defs", template.get("definitions", {})).get("task", {})
    limits = task.get("properties", {}).get("resource_limits")
    if not isinstance(limits, dict):
        raise ESAAError("CONTRACT_MIGRATE_INVALID", "packaged roadmap schema lacks resource_limits")
    return copy.deepcopy(limits)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ESAAError("CONTRACT_MIGRATE_INVALID", f"unreadable schema: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ESAAError("CONTRACT_MIGRATE_INVALID", f"schema must be an object: {path.name}")
    return payload


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _task_properties(schema: dict[str, Any]) -> dict[str, Any] | None:
    defs = schema.get("$defs", {}).get("task", {}).get("properties")
    if isinstance(defs, dict):
        return defs
    items = schema.get("properties", {}).get("tasks", {}).get("items", {})
    props = items.get("properties")
    return props if isinstance(props, dict) else None


def _patch_agent_result(schema: dict[str, Any]) -> bool:
    items = schema.get("properties", {}).get("file_updates", {}).get("items")
    if not isinstance(items, dict) or not isinstance(items.get("oneOf"), list):
        raise ESAAError(
            "CONTRACT_MIGRATE_CONFLICT",
            "agent_result.schema.json file_updates.items.oneOf is absent or customized incompatibly",
        )
    existing = [
        arm
        for arm in items["oneOf"]
        if isinstance(arm, dict)
        and ("binary" in arm.get("required", []) or "binary" in arm.get("properties", {}))
    ]
    wanted = _packaged_binary_arm()
    if existing:
        if len(existing) == 1 and existing[0] == wanted:
            return False
        raise ESAAError(
            "CONTRACT_MIGRATE_CONFLICT",
            "custom binary file_updates variant conflicts with packaged schema",
        )
    items["oneOf"].append(wanted)
    return True


def _patch_roadmap(schema: dict[str, Any]) -> bool:
    props = _task_properties(schema)
    if props is None:
        raise ESAAError(
            "CONTRACT_MIGRATE_CONFLICT",
            "roadmap.schema.json task properties are absent or customized incompatibly",
        )
    wanted = _packaged_resource_limits()
    if "resource_limits" in props:
        if props["resource_limits"] == wanted:
            return False
        raise ESAAError(
            "CONTRACT_MIGRATE_CONFLICT",
            "custom resource_limits schema conflicts with packaged schema",
        )
    props["resource_limits"] = wanted
    return True


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".esaa-schema-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _backup_dir(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ".roadmap" / "backups" / "contracts" / stamp


def migrate_active_contracts(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Patch active schemas in place. Idempotent when the required arms already exist."""
    root = Path(root)
    roadmap_dir = root / ".roadmap"
    if not roadmap_dir.is_dir():
        raise ESAAError("ROADMAP_DIR_MISSING", f".roadmap not found under {root}")

    planned: list[dict[str, Any]] = []
    unchanged: list[str] = []
    patched_docs: list[tuple[str, Path, dict[str, Any], str]] = []

    for name, patcher in (
        ("agent_result.schema.json", _patch_agent_result),
        ("roadmap.schema.json", _patch_roadmap),
    ):
        path = roadmap_dir / name
        if not path.exists():
            raise ESAAError("SCHEMA_MISSING", f"active schema missing: {name}")
        original_text = path.read_text(encoding="utf-8")
        schema = _load_json(path)
        changed = patcher(schema)
        if not changed:
            unchanged.append(f".roadmap/{name}")
            continue
        Draft202012Validator.check_schema(schema)
        new_text = _dump_json(schema)
        planned.append(
            {
                "path": f".roadmap/{name}",
                "before_sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
                "after_sha256": hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
            }
        )
        patched_docs.append((name, path, schema, original_text))

    result: dict[str, Any] = {
        "status": "migrated" if planned else "unchanged",
        "dry_run": dry_run,
        "files_changed": [item["path"] for item in planned],
        "files_unchanged": unchanged,
        "protected_paths": list(PROTECTED_RELATIVE_PATHS),
        "changes": planned,
    }
    if dry_run or not planned:
        return result

    backup = _backup_dir(root)
    backup.mkdir(parents=True, exist_ok=True)
    for name, path, schema, original_text in patched_docs:
        (backup / name).write_text(original_text, encoding="utf-8", newline="\n")
        _write_atomic(path, _dump_json(schema))
    result["backup_dir"] = str(backup.relative_to(root)).replace("\\", "/")
    return result


def revert_active_contracts(root: Path, backup_dir: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Restore allowlisted schemas from a migrate backup directory."""
    root = Path(root)
    source = Path(backup_dir)
    if not source.is_absolute():
        source = root / source
    if not source.is_dir():
        raise ESAAError("CONTRACT_MIGRATE_INVALID", "backup directory does not exist")
    restored: list[str] = []
    for name in MIGRATABLE_SCHEMAS:
        src = source / name
        dest = root / ".roadmap" / name
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        Draft202012Validator.check_schema(_load_json(src))
        restored.append(f".roadmap/{name}")
        if not dry_run:
            _write_atomic(dest, text if text.endswith("\n") else text + "\n")
    if not restored:
        raise ESAAError("CONTRACT_MIGRATE_INVALID", "backup directory has no migratable schemas")
    return {"status": "reverted", "dry_run": dry_run, "files_changed": restored, "from": str(source)}
