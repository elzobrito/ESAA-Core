from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from .boundary_paths import is_governed_state_path, pattern_targets_governed_state
from .errors import ESAAError

PLUGIN_LOCK_SCHEMA = "esaa-plugins-lock/v1"
ROADMAP_LOCK_SCHEMA = "esaa-roadmaps-lock/v1"
PLUGIN_SCHEMA = "esaa-plugin/v1"

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LOCAL_TASK_RE = re.compile(r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_DANGEROUS_ALLOWED_WRITE = {"**", "**/*"}


def _roadmap_dir(root: Path) -> Path:
    return root / ".roadmap"


def _plugin_inputs_dir(root: Path) -> Path:
    return _roadmap_dir(root) / "plugin-inputs"


def _plugins_lock_path(root: Path) -> Path:
    return _roadmap_dir(root) / "plugins.lock.json"


def _roadmaps_lock_path(root: Path) -> Path:
    return _roadmap_dir(root) / "roadmaps.lock.json"


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundled_plugins_dir(repo_root: Path | None = None) -> Path:
    source_tree = (repo_root or _default_repo_root()) / "src" / "esaa" / "bundled_plugins"
    if source_tree.exists():
        return source_tree
    return Path(__file__).resolve().parent / "bundled_plugins"


def _external_plugins_dir() -> Path:
    override = os.environ.get("ESAA_PLUGINS_HOME")
    if override:
        return Path(override)
    return Path.home() / ".esaa" / "plugins"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ESAAError("PLUGIN_NOT_FOUND", f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ESAAError("PLUGIN_INVALID_JSON", f"{path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ESAAError("PLUGIN_INVALID_JSON", f"{path}: expected object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_posix_path(value: str) -> str:
    return value.replace("\\", "/")


def _validate_relative_path(value: str, label: str, *, allow_uri: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must be a non-empty relative path")
    if "://" in value:
        if allow_uri and value.startswith("runtime://"):
            return value
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must be a relative path: {value}")
    normalized = _as_posix_path(value)
    path = PurePosixPath(normalized)
    if path.is_absolute() or _WINDOWS_ABSOLUTE_RE.match(value) or ".." in path.parts:
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must stay inside the plugin/workspace: {value}")
    return normalized


def _validate_output_path(value: str, label: str) -> str:
    normalized = _validate_relative_path(value, label, allow_uri=True)
    if normalized.startswith("runtime://"):
        return normalized
    if is_governed_state_path(normalized):
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} cannot target governed ESAA state: {value}")
    return normalized


def _validate_glob_pattern(value: str, label: str) -> str:
    normalized = _validate_relative_path(value, label)
    if normalized.startswith("runtime://"):
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must be a relative glob pattern: {value}")
    if normalized in _DANGEROUS_ALLOWED_WRITE:
        raise ESAAError(
            "PLUGIN_SCHEMA_INVALID", f"{label} uses dangerous wildcard without policy opt-in: {value}"
        )
    if pattern_targets_governed_state(normalized):
        raise ESAAError("PLUGIN_SCHEMA_INVALID", f"{label} cannot target governed ESAA state: {value}")
    return normalized


def _resolve_workspace_file(root: Path, path_arg: str, label: str) -> tuple[Path, str]:
    normalized = _validate_relative_path(path_arg, label)
    candidate = Path(normalized)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / normalized).resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must stay inside workspace: {path_arg}") from exc
    if not resolved.is_file():
        raise ESAAError("PLUGIN_NOT_FOUND", f"file not found: {path_arg}")
    return resolved, resolved.relative_to(root_resolved).as_posix()


def _read_plugins_lock(root: Path) -> dict[str, Any]:
    path = _plugins_lock_path(root)
    if not path.exists():
        return {"schema_version": PLUGIN_LOCK_SCHEMA, "plugins": []}
    payload = _read_json(path)
    if payload.get("schema_version") != PLUGIN_LOCK_SCHEMA:
        raise ESAAError("PLUGIN_LOCK_INVALID", "plugins.lock.json schema_version is invalid")
    if not isinstance(payload.get("plugins"), list):
        raise ESAAError("PLUGIN_LOCK_INVALID", "plugins.lock.json plugins must be an array")
    return payload


def _write_plugins_lock(root: Path, payload: dict[str, Any]) -> None:
    _write_json(_plugins_lock_path(root), payload)


def _read_roadmaps_lock(root: Path) -> dict[str, Any]:
    path = _roadmaps_lock_path(root)
    if not path.exists():
        return {"schema_version": ROADMAP_LOCK_SCHEMA, "roadmaps": []}
    payload = _read_json(path)
    if payload.get("schema_version") != ROADMAP_LOCK_SCHEMA:
        raise ESAAError("ROADMAP_LOCK_INVALID", "roadmaps.lock.json schema_version is invalid")
    if not isinstance(payload.get("roadmaps"), list):
        raise ESAAError("ROADMAP_LOCK_INVALID", "roadmaps.lock.json roadmaps must be an array")
    return payload


def _has_plugin_or_roadmap_events(events: list[dict[str, Any]]) -> bool:
    return any(str(ev.get("action", "")).startswith(("plugin.", "roadmap.")) for ev in events)


def _store_events_if_present(root: Path) -> list[dict[str, Any]]:
    from .constants import EVENT_STORE_PATH
    from .store_runtime import parse_event_store

    if not (root / EVENT_STORE_PATH).exists():
        return []
    return parse_event_store(root)


def _effective_plugins_lock(root: Path) -> dict[str, Any]:
    from .projector import project_plugins_lock

    events = _store_events_if_present(root)
    if _has_plugin_or_roadmap_events(events):
        return project_plugins_lock(events)
    return _read_plugins_lock(root)


def _effective_roadmaps_lock(root: Path) -> dict[str, Any]:
    from .projector import project_roadmaps_lock

    events = _store_events_if_present(root)
    if _has_plugin_or_roadmap_events(events):
        return project_roadmaps_lock(events)
    return _read_roadmaps_lock(root)


def _adoption_events(
    root: Path, current_events: list[dict[str, Any]], start_seq: int
) -> list[dict[str, Any]]:
    from .events import make_event

    if _has_plugin_or_roadmap_events(current_events):
        return []
    adopted: list[dict[str, Any]] = []
    seq = start_seq
    for plugin in _read_plugins_lock(root)["plugins"]:
        adopted.append(make_event(seq, "orchestrator", "plugin.install", dict(plugin)))
        seq += 1
    for item in _read_roadmaps_lock(root)["roadmaps"]:
        activate_payload = {
            "plugin_id": item["plugin_id"],
            "plugin_version": item.get("plugin_version", ""),
            "execution_id": item["execution_id"],
            "roadmap": item["roadmap"],
            "input": item.get("input"),
            "content_hash": item["content_hash"],
            "status": "active",
        }
        adopted.append(make_event(seq, "orchestrator", "roadmap.activate", activate_payload))
        seq += 1
        if item.get("status") == "paused":
            adopted.append(
                make_event(
                    seq,
                    "orchestrator",
                    "roadmap.pause",
                    {"plugin_id": item["plugin_id"], "execution_id": item["execution_id"]},
                )
            )
            seq += 1
    return adopted


def _commit_plugin_events(
    root: Path,
    new_events: list[tuple[str, dict[str, Any]]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from .events import make_event
    from .orchestrator_commit import commit_orchestrator_events
    from .projector import write_lock_projections
    from .store_runtime import append_transactional, next_event_seq, parse_event_store

    current_events = _store_events_if_present(root)
    seq = next_event_seq(current_events)
    candidates = _adoption_events(root, current_events, seq)
    seq += len(candidates)
    for action, payload in new_events:
        candidates.append(make_event(seq, "orchestrator", action, payload))
        seq += 1

    def _postcommit() -> None:
        write_lock_projections(root, parse_event_store(root))

    return commit_orchestrator_events(
        root,
        candidates,
        append_transactional,
        dry_run=dry_run,
        postcommit=_postcommit if not dry_run else None,
    )


def _validate_kebab(value: str, label: str) -> None:
    if not _KEBAB_RE.match(value):
        raise ESAAError("PLUGIN_INVALID_ID", f"{label} must be kebab-case: {value}")


def effective_task_id(plugin_id: str, execution_id: str, local_task_id: str) -> str:
    _validate_kebab(plugin_id, "plugin_id")
    _validate_kebab(execution_id, "execution_id")
    if ":" in local_task_id or not _LOCAL_TASK_RE.match(local_task_id):
        raise ESAAError("PLUGIN_INVALID_ID", f"local_task_id is invalid: {local_task_id}")
    return f"{plugin_id}-{execution_id}-{local_task_id}"


def _hash_dir(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = file_path.relative_to(path).as_posix()
        if "__pycache__" in file_path.parts or rel.endswith((".pyc", ".pyo")):
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _plugin_schema(repo_root: Path | None = None) -> dict[str, Any] | None:
    schema_path = (
        (repo_root or _default_repo_root()) / "src" / "esaa" / "templates" / "esaa-plugin.schema.json"
    )
    if not schema_path.exists():
        return None
    return _read_json(schema_path)


def _validate_manifest_shape(manifest: dict[str, Any], repo_root: Path | None = None) -> None:
    schema = _plugin_schema(repo_root)
    if schema is not None:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(manifest), key=lambda error: list(error.path)
        )
        if errors:
            error = errors[0]
            loc = "/".join(str(part) for part in error.path) or "<root>"
            raise ESAAError("PLUGIN_SCHEMA_INVALID", f"plugin.json {loc}: {error.message}")
        return

    required = {"schema_version", "id", "name", "version", "kind", "entrypoints", "task_id_namespace"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ESAAError("PLUGIN_SCHEMA_INVALID", "plugin.json missing: " + ", ".join(missing))


def validate_plugin_dir(plugin_dir: Path, repo_root: Path | None = None) -> dict[str, Any]:
    if not plugin_dir.is_dir():
        raise ESAAError("PLUGIN_NOT_A_DIRECTORY", f"plugin package must be a directory: {plugin_dir}")
    manifest_path = plugin_dir / "plugin.json"
    manifest = _read_json(manifest_path)
    _validate_manifest_shape(manifest, repo_root)

    plugin_id = manifest["id"]
    _validate_kebab(plugin_id, "plugin_id")
    if not _SEMVER_RE.match(manifest["version"]):
        raise ESAAError("PLUGIN_SCHEMA_INVALID", f"invalid plugin version: {manifest['version']}")
    if manifest.get("schema_version") != PLUGIN_SCHEMA:
        raise ESAAError(
            "PLUGIN_SCHEMA_INVALID", f"unsupported plugin schema: {manifest.get('schema_version')}"
        )
    if manifest.get("kind") != "roadmap_plugin":
        raise ESAAError("PLUGIN_SCHEMA_INVALID", f"unsupported plugin kind: {manifest.get('kind')}")

    external_target_ids: set[str] = set()
    for idx, target in enumerate(manifest.get("external_targets", []) or []):
        target_id = target["id"]
        if target_id in external_target_ids:
            raise ESAAError("PLUGIN_SCHEMA_INVALID", f"duplicate external target: {target_id}")
        external_target_ids.add(target_id)
        _validate_relative_path(target["runtime_contract"], f"external_targets[{idx}].runtime_contract")
        for pattern_idx, pattern in enumerate(target.get("allowed_write", [])):
            _validate_glob_pattern(pattern, f"external_targets[{idx}].allowed_write[{pattern_idx}]")

    forbidden = [
        ".roadmap/activity.jsonl",
        ".roadmap/roadmap.json",
        ".roadmap/issues.json",
        ".roadmap/lessons.json",
    ]
    for rel in forbidden:
        if (plugin_dir / rel).exists():
            raise ESAAError("PLUGIN_FORBIDDEN_FILE", f"plugin contains forbidden file: {rel}")

    entrypoints = manifest["entrypoints"]
    for key in ("roadmap", "input_example", "input_schema"):
        if key in entrypoints:
            entrypoints[key] = _validate_relative_path(entrypoints[key], f"entrypoints.{key}")

    roadmap_rel = entrypoints["roadmap"]
    roadmap_path = plugin_dir / roadmap_rel
    roadmap = _read_json(roadmap_path)
    if not isinstance(roadmap.get("project"), dict):
        raise ESAAError("PLUGIN_ROADMAP_INVALID", "roadmap.template.json project must be an object")
    tasks = roadmap.get("tasks")
    if not isinstance(tasks, list):
        raise ESAAError("PLUGIN_ROADMAP_INVALID", "roadmap.template.json tasks must be an array")
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ESAAError("PLUGIN_ROADMAP_INVALID", f"tasks[{idx}] must be an object")
        for key in ("task_id", "task_kind", "title", "description", "depends_on", "outputs"):
            if key not in task:
                raise ESAAError("PLUGIN_ROADMAP_INVALID", f"tasks[{idx}] missing {key}")
        if not isinstance(task["depends_on"], list):
            raise ESAAError("PLUGIN_ROADMAP_INVALID", f"tasks[{idx}].depends_on must be an array")
        outputs = task["outputs"]
        if not isinstance(outputs, dict) or not isinstance(outputs.get("files"), list):
            raise ESAAError("PLUGIN_ROADMAP_INVALID", f"tasks[{idx}].outputs.files must be an array")
        for out_idx, output_path in enumerate(outputs["files"]):
            if not isinstance(output_path, str):
                raise ESAAError(
                    "PLUGIN_ROADMAP_INVALID", f"tasks[{idx}].outputs.files[{out_idx}] must be a string"
                )
            _validate_output_path(output_path, f"tasks[{idx}].outputs.files[{out_idx}]")
        boundary_grant = task.get("boundary_grant", [])
        if not isinstance(boundary_grant, list):
            raise ESAAError("PLUGIN_ROADMAP_INVALID", f"tasks[{idx}].boundary_grant must be an array")
        for grant_idx, pattern in enumerate(boundary_grant):
            if not isinstance(pattern, str):
                raise ESAAError(
                    "PLUGIN_ROADMAP_INVALID",
                    f"tasks[{idx}].boundary_grant[{grant_idx}] must be a string",
                )
            _validate_glob_pattern(pattern, f"tasks[{idx}].boundary_grant[{grant_idx}]")
        external_files = outputs.get("external_files", [])
        if external_files:
            if not isinstance(external_files, list):
                raise ESAAError(
                    "PLUGIN_ROADMAP_INVALID", f"tasks[{idx}].outputs.external_files must be an array"
                )
            for ext_idx, external in enumerate(external_files):
                if not isinstance(external, dict):
                    raise ESAAError(
                        "PLUGIN_ROADMAP_INVALID",
                        f"tasks[{idx}].outputs.external_files[{ext_idx}] must be an object",
                    )
                target_id = external.get("target") or outputs.get("target")
                if target_id not in external_target_ids:
                    raise ESAAError(
                        "PLUGIN_ROADMAP_INVALID",
                        f"tasks[{idx}].outputs.external_files[{ext_idx}] target is not declared",
                    )
                path = external.get("path")
                if not isinstance(path, str):
                    raise ESAAError(
                        "PLUGIN_ROADMAP_INVALID",
                        f"tasks[{idx}].outputs.external_files[{ext_idx}].path must be a string",
                    )
                _validate_output_path(path, f"tasks[{idx}].outputs.external_files[{ext_idx}].path")
        effective_task_id(plugin_id, "default", task["task_id"])

    input_schema = entrypoints.get("input_schema")
    if input_schema and not (plugin_dir / input_schema).exists():
        raise ESAAError("PLUGIN_SCHEMA_INVALID", f"input schema not found: {input_schema}")
    input_example = entrypoints.get("input_example")
    if input_example and not (plugin_dir / input_example).exists():
        raise ESAAError("PLUGIN_SCHEMA_INVALID", f"input example not found: {input_example}")

    return {
        "id": plugin_id,
        "name": manifest["name"],
        "version": manifest["version"],
        "kind": manifest["kind"],
        "path": str(plugin_dir),
        "manifest": manifest,
        "content_hash": _hash_dir(plugin_dir),
        "valid": True,
    }


def _available_plugin_dirs(
    repo_root: Path | None = None, source_filter: str | None = None
) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    bundled = _bundled_plugins_dir(repo_root)
    if source_filter in {None, "bundled"} and bundled.exists():
        for path in sorted(p for p in bundled.iterdir() if p.is_dir() and p.name != "__pycache__"):
            out.append(("bundled", path))
    external = _external_plugins_dir()
    if source_filter in {None, "external"} and external.exists():
        for plugin_id_dir in sorted(p for p in external.iterdir() if p.is_dir() and p.name != "__pycache__"):
            version_dirs = [p for p in plugin_id_dir.iterdir() if p.is_dir() and p.name != "__pycache__"]
            for path in sorted(version_dirs):
                out.append(("external", path))
    return out


def _looks_like_path(ref: str) -> bool:
    return any(sep in ref for sep in ("/", "\\")) or ref in {".", ".."} or ref.startswith(".")


def _resolve_plugin_dir_ref(root: Path, ref: str) -> Path:
    raw = Path(ref)
    candidates: list[Path]
    if raw.is_absolute():
        candidates = [raw]
    else:
        candidates = [root / raw, Path.cwd() / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _find_plugin_ref(
    root: Path, plugin_ref: str, repo_root: Path | None = None
) -> tuple[str, Path, dict[str, Any]]:
    if Path(plugin_ref).is_absolute() or _looks_like_path(plugin_ref):
        path = _resolve_plugin_dir_ref(root, plugin_ref)
        info = validate_plugin_dir(path, repo_root)
        return "local", path, info
    return _find_available_plugin(plugin_ref, repo_root)


def _find_available_plugin(plugin_id: str, repo_root: Path | None = None) -> tuple[str, Path, dict[str, Any]]:
    _validate_kebab(plugin_id, "plugin_id")
    for source, path in _available_plugin_dirs(repo_root):
        try:
            info = validate_plugin_dir(path, repo_root)
        except ESAAError:
            continue
        if info["id"] == plugin_id:
            return source, path, info
    raise ESAAError("PLUGIN_NOT_FOUND", f"plugin not found: {plugin_id}")


def scaffold_plugin(
    root: Path,
    plugin_id: str,
    *,
    directory: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    _validate_kebab(plugin_id, "plugin_id")
    target = (root / (directory or plugin_id)).resolve()
    if target.exists():
        raise ESAAError("PLUGIN_TARGET_EXISTS", f"plugin target already exists: {target}")

    name = " ".join(part.capitalize() for part in plugin_id.split("-"))
    manifest = {
        "schema_version": PLUGIN_SCHEMA,
        "id": plugin_id,
        "name": name,
        "version": "1.0.0",
        "kind": "roadmap_plugin",
        "esaa_core": {"min_version": "0.5.0", "max_version": "<0.6.0"},
        "entrypoints": {
            "roadmap": "roadmap.template.json",
            "input_example": f"inputs/{plugin_id}.local.example.json",
            "input_schema": f"schemas/{plugin_id}-input.schema.json",
        },
        "task_id_namespace": plugin_id,
        "capabilities": ["planned_tasks", "local_input", "runtime_contract"],
    }
    roadmap = {
        "project": {"name": name, "audit_scope": plugin_id},
        "tasks": [
            {
                "task_id": "T-001",
                "task_kind": "spec",
                "title": f"Define {plugin_id} baseline",
                "description": f"Document the governed {plugin_id} baseline.",
                "depends_on": [],
                "outputs": {"files": [f"docs/{plugin_id}/baseline.md"]},
            }
        ],
    }
    input_example = {"target": "local"}
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["target"],
        "properties": {"target": {"type": "string", "minLength": 1}},
    }

    _write_json(target / "plugin.json", manifest)
    _write_json(target / "roadmap.template.json", roadmap)
    _write_json(target / "inputs" / f"{plugin_id}.local.example.json", input_example)
    _write_json(target / "schemas" / f"{plugin_id}-input.schema.json", input_schema)
    (target / "README.md").write_text(
        f"# {name}\n\nESAA roadmap plugin package. Validate with `esaa plugin validate ./{plugin_id}`.\n",
        encoding="utf-8",
    )
    info = validate_plugin_dir(target, repo_root)
    return {"status": "created", "plugin": info["id"], "path": str(target), "valid": True}


def list_available_plugins(
    repo_root: Path | None = None, *, source_filter: str | None = None
) -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []
    for source, path in _available_plugin_dirs(repo_root, source_filter=source_filter):
        try:
            info = validate_plugin_dir(path, repo_root)
        except ESAAError as exc:
            plugins.append({"path": str(path), "source": source, "valid": False, "error_code": exc.code})
            continue
        plugins.append(
            {
                "id": info["id"],
                "name": info["name"],
                "version": info["version"],
                "source": source,
                "content_hash": info["content_hash"],
            }
        )
    return plugins


def validate_plugin(root: Path, plugin_ref: str, repo_root: Path | None = None) -> dict[str, Any]:
    source, path, info = _find_plugin_ref(root, plugin_ref, repo_root)
    return {
        "id": info["id"],
        "name": info["name"],
        "version": info["version"],
        "source": source,
        "content_hash": info["content_hash"],
        "valid": True,
        "path": str(path),
    }


def diagnose_plugin(root: Path, plugin_ref: str, repo_root: Path | None = None) -> dict[str, Any]:
    checks = [
        {"name": "directory", "status": "pending"},
        {"name": "manifest", "status": "pending"},
        {"name": "roadmap", "status": "pending"},
        {"name": "input_schema", "status": "pending"},
        {"name": "input_example", "status": "pending"},
        {"name": "path_safety", "status": "pending"},
    ]
    try:
        source, path, info = _find_plugin_ref(root, plugin_ref, repo_root)
    except ESAAError as exc:
        failed = checks[0] if exc.code == "PLUGIN_NOT_A_DIRECTORY" else checks[1]
        failed["status"] = "error"
        return {
            "status": "invalid",
            "plugin": plugin_ref,
            "checks": checks,
            "errors": [{"code": exc.code, "message": exc.message}],
        }

    for check in checks:
        check["status"] = "ok"
    return {
        "status": "ok",
        "plugin": info["id"],
        "source": source,
        "path": str(path),
        "content_hash": info["content_hash"],
        "checks": checks,
        "errors": [],
    }


def list_installed_plugins(root: Path, repo_root: Path | None = None) -> list[dict[str, Any]]:
    return list(_effective_plugins_lock(root)["plugins"])


def install_plugin(
    root: Path, plugin_ref: str, repo_root: Path | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    source, path, info = _find_plugin_ref(root, plugin_ref, repo_root)
    plugin_id = info["id"]
    lock = _effective_plugins_lock(root)
    already_installed = any(plugin["id"] == plugin_id for plugin in lock["plugins"])
    manifest_path = f"plugins/{plugin_id}/plugin.json" if source == "bundled" else str(path / "plugin.json")
    installed = {
        "id": info["id"],
        "name": info["name"],
        "version": info["version"],
        "source": source,
        "content_hash": info["content_hash"],
        "manifest_path": manifest_path,
    }
    action = "plugin.update" if already_installed else "plugin.install"
    commit = _commit_plugin_events(root, [(action, installed)], dry_run=dry_run)
    return {
        "status": "dry_run" if dry_run else "installed",
        "action": action,
        "plugin": installed,
        "dry_run": dry_run,
        "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
    }


def update_plugin(
    root: Path, plugin_ref: str, repo_root: Path | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    source, path, info = _find_plugin_ref(root, plugin_ref, repo_root)
    plugin_id = info["id"]
    _installed_plugin(root, plugin_id)
    manifest_path = f"plugins/{plugin_id}/plugin.json" if source == "bundled" else str(path / "plugin.json")
    updated = {
        "id": info["id"],
        "name": info["name"],
        "version": info["version"],
        "source": source,
        "content_hash": info["content_hash"],
        "manifest_path": manifest_path,
    }
    commit = _commit_plugin_events(root, [("plugin.update", updated)], dry_run=dry_run)
    return {
        "status": "dry_run" if dry_run else "updated",
        "action": "plugin.update",
        "plugin": updated,
        "dry_run": dry_run,
        "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
    }


def remove_plugin(
    root: Path, plugin_id: str, repo_root: Path | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    _validate_kebab(plugin_id, "plugin_id")
    lock = _effective_plugins_lock(root)
    before = len(lock["plugins"])
    removed = 1 if any(plugin["id"] == plugin_id for plugin in lock["plugins"]) else 0
    commit = _commit_plugin_events(root, [("plugin.remove", {"plugin_id": plugin_id})], dry_run=dry_run)
    return {
        "status": "dry_run" if dry_run else "removed",
        "removed": removed if before else 0,
        "plugin_id": plugin_id,
        "dry_run": dry_run,
        "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
    }


def _installed_plugin(root: Path, plugin_id: str) -> dict[str, Any]:
    for plugin in _effective_plugins_lock(root)["plugins"]:
        if plugin["id"] == plugin_id:
            return plugin
    raise ESAAError("PLUGIN_NOT_INSTALLED", f"plugin is not installed: {plugin_id}")


def _plugin_dir_from_lock(plugin: dict[str, Any], repo_root: Path | None = None) -> Path:
    manifest_path = Path(plugin["manifest_path"])
    if plugin.get("source") == "bundled" and not manifest_path.is_absolute():
        return _bundled_plugins_dir(repo_root) / plugin["id"]
    if manifest_path.exists():
        return manifest_path.parent
    if plugin.get("source") == "bundled":
        return _bundled_plugins_dir(repo_root) / plugin["id"]
    raise ESAAError("PLUGIN_NOT_FOUND", f"installed plugin path is missing: {plugin['id']}")


def _validate_input_file(plugin_dir: Path, manifest: dict[str, Any], input_file: Path) -> None:
    schema_rel = manifest["entrypoints"].get("input_schema")
    if not schema_rel:
        return
    schema = _read_json(plugin_dir / schema_rel)
    payload = _read_json(input_file)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: (0 if error.validator == "required" else 1, list(error.path)),
    )
    if errors:
        error = errors[0]
        loc = "/".join(str(part) for part in error.path) or "<root>"
        raise ESAAError("PLUGIN_INPUT_INVALID", f"{input_file} {loc}: {error.message}")


def activate_roadmap(
    root: Path,
    plugin_id: str,
    *,
    execution_id: str = "default",
    input_path: str | None = None,
    repo_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _validate_kebab(execution_id, "execution_id")
    plugin = _installed_plugin(root, plugin_id)
    plugin_dir = _plugin_dir_from_lock(plugin, repo_root)
    info = validate_plugin_dir(plugin_dir, repo_root)
    manifest = info["manifest"]

    input_rel = input_path
    example_rel = manifest["entrypoints"].get("input_example")
    input_file: Path | None = None
    input_source_for_hash: Path | None = None
    if input_rel is None and example_rel:
        input_name = f"{plugin_id}.{execution_id}.local.json"
        input_dest = _plugin_inputs_dir(root) / input_name
        if not dry_run:
            input_dest.parent.mkdir(parents=True, exist_ok=True)
            if not input_dest.exists():
                shutil.copy2(plugin_dir / example_rel, input_dest)
            input_file = input_dest
            input_source_for_hash = input_dest
        else:
            input_file = input_dest if input_dest.exists() else (plugin_dir / example_rel)
            input_source_for_hash = input_file
        input_rel = str(input_dest.relative_to(root)).replace("\\", "/")
    elif input_rel is not None:
        input_file, input_rel = _resolve_workspace_file(root, input_rel, "roadmap input")
        input_source_for_hash = input_file

    if input_file is not None:
        _validate_input_file(plugin_dir, manifest, input_file)

    input_hash = (
        "sha256:" + hashlib.sha256(input_source_for_hash.read_bytes()).hexdigest()
        if input_source_for_hash is not None
        else None
    )
    entry = {
        "plugin_id": plugin_id,
        "plugin_version": plugin["version"],
        "execution_id": execution_id,
        "roadmap": manifest["entrypoints"]["roadmap"],
        "input": input_rel,
        "content_hash": info["content_hash"],
        "status": "active",
    }
    event_payload = {**entry, "input_hash": input_hash}
    commit = _commit_plugin_events(root, [("roadmap.activate", event_payload)], dry_run=dry_run)
    return {
        "status": "dry_run" if dry_run else "active",
        **entry,
        "dry_run": dry_run,
        "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
    }


def set_roadmap_status(
    root: Path,
    plugin_id: str,
    execution_id: str,
    status: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if status not in {"active", "paused", "deactivated"}:
        raise ESAAError("ROADMAP_STATUS_INVALID", f"invalid roadmap status: {status}")
    lock = _effective_roadmaps_lock(root)
    for item in lock["roadmaps"]:
        if item["plugin_id"] == plugin_id and item["execution_id"] == execution_id:
            action = {
                "paused": "roadmap.pause",
                "active": "roadmap.resume",
                "deactivated": "roadmap.deactivate",
            }[status]
            commit = _commit_plugin_events(
                root,
                [(action, {"plugin_id": plugin_id, "execution_id": execution_id})],
                dry_run=dry_run,
            )
            updated = dict(item)
            updated["status"] = status
            return {
                **updated,
                "status": "dry_run" if dry_run else status,
                "target_status": status,
                "dry_run": dry_run,
                "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
            }
    raise ESAAError("ROADMAP_NOT_FOUND", f"roadmap execution not found: {plugin_id}/{execution_id}")


def deactivate_roadmap(
    root: Path, plugin_id: str, execution_id: str = "default", *, dry_run: bool = False
) -> dict[str, Any]:
    lock = _effective_roadmaps_lock(root)
    removed = sum(
        1
        for item in lock["roadmaps"]
        if item["plugin_id"] == plugin_id and item["execution_id"] == execution_id
    )
    commit = _commit_plugin_events(
        root,
        [("roadmap.deactivate", {"plugin_id": plugin_id, "execution_id": execution_id})],
        dry_run=dry_run,
    )
    return {
        "status": "dry_run" if dry_run else "deactivated",
        "removed": removed,
        "plugin_id": plugin_id,
        "execution_id": execution_id,
        "dry_run": dry_run,
        "events_appended": commit.get("would_append_events", commit.get("events_appended", 0)),
    }


def list_roadmaps(root: Path, *, detail: bool = False, repo_root: Path | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _effective_roadmaps_lock(root)["roadmaps"]:
        row = dict(item)
        if detail and item.get("status") == "active":
            seed = _tasks_for_roadmap_entry(root, item, repo_root)
            row["tasks"] = seed
        items.append(row)
    return items


def _tasks_for_roadmap_entry(
    root: Path, entry: dict[str, Any], repo_root: Path | None = None
) -> list[dict[str, Any]]:
    plugin = _installed_plugin(root, entry["plugin_id"])
    plugin_dir = _plugin_dir_from_lock(plugin, repo_root)
    roadmap = _read_json(plugin_dir / entry["roadmap"])
    tasks: list[dict[str, Any]] = []
    for raw_task in roadmap.get("tasks", []):
        local_task_id = raw_task["task_id"]
        task = {
            "task_id": effective_task_id(entry["plugin_id"], entry["execution_id"], local_task_id),
            "task_kind": raw_task["task_kind"],
            "title": raw_task["title"],
            "description": raw_task.get("description", raw_task["title"]),
            "depends_on": [
                effective_task_id(entry["plugin_id"], entry["execution_id"], dep)
                for dep in raw_task.get("depends_on", [])
            ],
            "targets": list(raw_task.get("targets", [])),
            "outputs": raw_task.get("outputs", {"files": []}),
            "plugin": {
                "id": entry["plugin_id"],
                "execution_id": entry["execution_id"],
                "local_task_id": local_task_id,
            },
        }
        if raw_task.get("boundary_grant"):
            task["boundary_grant"] = [
                _validate_glob_pattern(pattern, f"tasks[{local_task_id}].boundary_grant[{index}]")
                for index, pattern in enumerate(raw_task["boundary_grant"])
            ]
        tasks.append(task)
    return tasks


def load_active_roadmap_tasks(root: Path, repo_root: Path | None = None) -> dict[str, Any] | None:
    lock = _effective_roadmaps_lock(root)
    active = [item for item in lock["roadmaps"] if item.get("status") == "active"]
    if not active:
        return None

    tasks: list[dict[str, Any]] = []
    project_names: list[str] = []
    for item in active:
        plugin = _installed_plugin(root, item["plugin_id"])
        plugin_dir = _plugin_dir_from_lock(plugin, repo_root)
        roadmap = _read_json(plugin_dir / item["roadmap"])
        project = roadmap.get("project", {}) or {}
        if project.get("name"):
            project_names.append(project["name"])
        tasks.extend(_tasks_for_roadmap_entry(root, item, repo_root))

    if not tasks:
        return None
    return {
        "project_name": ", ".join(project_names) if project_names else None,
        "audit_scope": "installed plugin roadmaps",
        "tasks": tasks,
    }


def _summarize_plugin_roadmap(
    root: Path,
    path: Path,
    projected_status: dict[str, str],
    detail: bool,
    grand_totals: dict[str, int],
) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    tasks = data.get("tasks") or []
    if not tasks:
        return None

    by_planned_status: dict[str, int] = {}
    by_live_status: dict[str, int] = {}
    in_projection = 0
    items: list[dict[str, Any]] = []

    for t in tasks:
        tid = t.get("task_id", "?")
        planned = t.get("status", "todo")
        live = projected_status.get(tid)
        by_planned_status[planned] = by_planned_status.get(planned, 0) + 1
        effective = live if live is not None else planned
        by_live_status[effective] = by_live_status.get(effective, 0) + 1
        grand_totals[effective] = grand_totals.get(effective, 0) + 1
        if live is not None:
            in_projection += 1
        if detail:
            items.append(
                {
                    "task_id": tid,
                    "title": t.get("title", ""),
                    "kind": t.get("task_kind"),
                    "planned_status": planned,
                    "live_status": live,
                }
            )

    return {
        "plugin_file": str(path.relative_to(root)).replace("\\", "/"),
        "tasks_declared": len(tasks),
        "in_projection": in_projection,
        "by_live_status": by_live_status,
        "by_planned_status": by_planned_status,
        **({"tasks": items} if detail else {}),
    }


def plugin_status(root: Path, detail: bool = False, plugin_filter: str | None = None) -> dict[str, Any]:
    """Cross-reference planned tasks (per-plugin) with projected state."""
    roadmap_dir = root / ".roadmap"
    if not roadmap_dir.is_dir():
        raise ESAAError("ROADMAP_DIR_MISSING", f".roadmap not found under {root}")

    projection_path = roadmap_dir / "roadmap.json"
    projected_status: dict[str, str] = {}
    if projection_path.is_file():
        try:
            proj = json.loads(projection_path.read_text(encoding="utf-8"))
            for t in proj.get("tasks", []):
                tid = t.get("task_id")
                if tid:
                    projected_status[tid] = t.get("status", "?")
        except (ValueError, OSError) as exc:
            raise ESAAError("PROJECTION_UNREADABLE", str(exc)) from exc

    plugins: list[dict[str, Any]] = []
    grand_totals: dict[str, int] = {}

    for path in sorted(roadmap_dir.glob("roadmap*.json")):
        if path.name == "roadmap.schema.json" or path.name.endswith(".template.json"):
            continue
        if plugin_filter and path.name != plugin_filter:
            continue
        summary = _summarize_plugin_roadmap(root, path, projected_status, detail, grand_totals)
        if summary is not None:
            plugins.append(summary)

    return {
        "root": str(root),
        "projection_present": projection_path.is_file(),
        "plugins": plugins,
        "grand_totals_by_live_status": grand_totals,
    }
