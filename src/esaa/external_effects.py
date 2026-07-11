from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from .boundary_paths import assert_writable_not_governed, path_within_scope
from .errors import ESAAError
from .plugins import _plugin_dir_from_lock, _read_json, _read_plugins_lock, _read_roadmaps_lock
from .runtime_policy import load_policy
from .utils import normalize_rel_path

DEFAULT_RUNTIME_PREFIXES = ["runtime://outputs."]
DANGEROUS_ALLOWED_WRITE = {"**", "**/*"}


def _external_policy(root: Path) -> dict[str, Any] | None:
    value = load_policy(root).get("external_effects")
    return value if isinstance(value, dict) else None


def _policy_bool(policy: dict[str, Any] | None, key: str, default: bool) -> bool:
    if policy is None:
        return default
    return bool(policy.get(key, default))


def _dangerous_allowed_write(pattern: str) -> bool:
    return pattern.replace("\\", "/").strip() in DANGEROUS_ALLOWED_WRITE


def _validate_allowed_write_patterns(patterns: list[str], allow_wildcard: bool, label: str) -> None:
    if allow_wildcard:
        return
    for pattern in patterns:
        if _dangerous_allowed_write(pattern):
            raise ESAAError(
                "PLUGIN_SCHEMA_INVALID", f"dangerous allowed_write wildcard requires policy opt-in: {label}"
            )


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern.replace("\\", "/")) for pattern in patterns)


def _task_external_specs(task: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = task.get("outputs", {}) or {}
    specs = outputs.get("external_files", []) or []
    return [spec for spec in specs if isinstance(spec, dict)]


def task_accepts_external_path(task: dict[str, Any], path: str) -> bool:
    return any(spec.get("path") == path for spec in _task_external_specs(task))


def _projected_task(root: Path, task_id: str) -> dict[str, Any] | None:
    roadmap_path = root / ".roadmap" / "roadmap.json"
    try:
        payload = json.loads(roadmap_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for task in payload.get("tasks", []) or []:
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return task
    return None


def _scope_allows(scope_patch: list[Any], path: str) -> bool:
    return any(path_within_scope(path, str(prefix)) for prefix in scope_patch)


def _external_specs_with_context(
    root: Path, task: dict[str, Any]
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    specs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
        spec["path"]: (spec, task) for spec in _task_external_specs(task) if isinstance(spec.get("path"), str)
    }

    if task.get("is_hotfix"):
        fixed_task_id = task.get("fixes")
        fixed_task = _projected_task(root, fixed_task_id) if isinstance(fixed_task_id, str) else None
        scope_patch = task.get("scope_patch", []) or []
        if fixed_task:
            for spec in _task_external_specs(fixed_task):
                path = spec.get("path")
                if isinstance(path, str) and _scope_allows(scope_patch, path):
                    specs[path] = (spec, fixed_task)
    return specs


def _installed_plugin(root: Path, plugin_id: str) -> dict[str, Any]:
    for plugin in _read_plugins_lock(root)["plugins"]:
        if plugin.get("id") == plugin_id:
            return plugin
    raise ESAAError("PLUGIN_NOT_INSTALLED", f"plugin is not installed: {plugin_id}")


def _active_roadmap_entry(root: Path, plugin_id: str, execution_id: str) -> dict[str, Any]:
    for entry in _read_roadmaps_lock(root)["roadmaps"]:
        if (
            entry.get("plugin_id") == plugin_id
            and entry.get("execution_id") == execution_id
            and entry.get("status") == "active"
        ):
            return entry
    raise ESAAError("ROADMAP_NOT_FOUND", f"active roadmap not found: {plugin_id}/{execution_id}")


def _runtime_parts(uri: str, prefixes: list[str]) -> tuple[str, str]:
    for prefix in prefixes:
        if uri.startswith(prefix):
            suffix = uri[len(prefix) :]
            parts = [part for part in suffix.split(".") if part]
            if not parts:
                raise ESAAError("PLUGIN_PATH_INVALID", f"runtime uri has no key: {uri}")
            namespace = prefix.removeprefix("runtime://").rstrip(".")
            return namespace, ".".join(parts)
    raise ESAAError("PLUGIN_PATH_INVALID", f"runtime uri prefix not allowed: {uri}")


def _read_nested(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ESAAError("PLUGIN_PATH_INVALID", f"runtime contract key not found: {dotted_path}")
        current = current[part]
    return current


def _safe_relative_path(value: str, label: str) -> str:
    rel = normalize_rel_path(value)
    if not rel or rel.startswith("/") or ":" in rel:
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} must be a relative path: {value}")
    parts = Path(rel).parts
    if any(part == ".." for part in parts):
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} cannot traverse outside target: {value}")
    return rel.replace("\\", "/")


def _resolve_under_root(root: Path, rel_path: str, label: str) -> Path:
    resolved = (root / rel_path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ESAAError("PLUGIN_PATH_INVALID", f"{label} resolved outside target root: {rel_path}") from exc
    return resolved


def _allowed_external_roots(workspace: Path, policy: dict[str, Any] | None) -> list[Path]:
    if policy is None:
        return []
    roots = policy.get("allowed_roots", []) or []
    if not isinstance(roots, list):
        raise ESAAError("PLUGIN_SCHEMA_INVALID", "external_effects.allowed_roots must be a list")
    out: list[Path] = []
    for entry in roots:
        if not isinstance(entry, str) or not entry.strip():
            continue
        raw = Path(entry)
        out.append((raw if raw.is_absolute() else workspace / raw).resolve())
    return out


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _target_root(
    workspace: Path,
    input_payload: dict[str, Any],
    root_input: str,
    policy: dict[str, Any] | None = None,
) -> Path:
    value = input_payload.get(root_input)
    if not isinstance(value, str) or not value.strip():
        raise ESAAError("PLUGIN_INPUT_INVALID", f"missing external target root input: {root_input}")
    raw = Path(value)
    resolved = (raw if raw.is_absolute() else workspace / raw).resolve()
    if policy is None:
        return resolved
    allowed_roots = _allowed_external_roots(workspace, policy)
    if not allowed_roots or not any(_is_relative_to(resolved, allowed) for allowed in allowed_roots):
        raise ESAAError("EXTERNAL_ROOT_NOT_ALLOWED", f"external target root is not allowed: {resolved}")
    return resolved


def _target_config(manifest: dict[str, Any], target_id: str) -> dict[str, Any]:
    for target in manifest.get("external_targets", []) or []:
        if target.get("id") == target_id:
            return target
    raise ESAAError("PLUGIN_SCHEMA_INVALID", f"external target not declared: {target_id}")


def _runtime_prefixes(target: dict[str, Any]) -> list[str]:
    values = target.get("runtime_uri_prefixes")
    if values is None and target.get("runtime_uri_prefix"):
        values = [target["runtime_uri_prefix"]]
    if values is None:
        values = DEFAULT_RUNTIME_PREFIXES
    return [str(value) for value in values]


def _load_external_context(
    root: Path, task: dict[str, Any], target_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plugin_info = task.get("plugin") or {}
    plugin_id = plugin_info.get("id")
    execution_id = plugin_info.get("execution_id", "default")
    if not plugin_id:
        raise ESAAError("PLUGIN_SCHEMA_INVALID", "external effects require plugin task metadata")

    plugin = _installed_plugin(root, plugin_id)
    plugin_dir = _plugin_dir_from_lock(plugin)
    manifest = _read_json(plugin_dir / "plugin.json")
    target = _target_config(manifest, target_id)
    roadmap_entry = _active_roadmap_entry(root, plugin_id, execution_id)
    input_rel = roadmap_entry.get("input")
    if not input_rel:
        raise ESAAError("PLUGIN_INPUT_INVALID", f"active roadmap missing input: {plugin_id}/{execution_id}")
    input_payload = json.loads((root / input_rel).read_text(encoding="utf-8"))
    if not isinstance(input_payload, dict):
        raise ESAAError("PLUGIN_INPUT_INVALID", f"plugin input must be an object: {input_rel}")
    return manifest, target, input_payload


def _runtime_contract(root: Path, target: dict[str, Any]) -> dict[str, Any]:
    contract_rel = target.get("runtime_contract")
    if not isinstance(contract_rel, str) or not contract_rel.strip():
        raise ESAAError("PLUGIN_SCHEMA_INVALID", "external target requires runtime_contract")
    contract_path = _resolve_under_root(
        root, _safe_relative_path(contract_rel, "runtime_contract"), "runtime_contract"
    )
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ESAAError("PLUGIN_NOT_FOUND", f"runtime contract not found: {contract_rel}") from exc
    except json.JSONDecodeError as exc:
        raise ESAAError("PLUGIN_INVALID_JSON", f"{contract_rel}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ESAAError("PLUGIN_INVALID_JSON", f"{contract_rel}: expected object")
    return payload


def resolve_external_file_updates(
    root: Path,
    task: dict[str, Any],
    file_updates: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not file_updates:
        return []

    external_by_path = _external_specs_with_context(root, task)
    external_policy = _external_policy(root)
    allow_wildcard = _policy_bool(external_policy, "allow_glob_wildcard", False)
    resolved: list[dict[str, Any]] = []
    for item in file_updates:
        path = item["path"]
        entry = external_by_path.get(path)
        if not entry:
            resolved.append(dict(item))
            continue
        spec, context_task = entry

        target_id = spec.get("target") or (context_task.get("outputs") or {}).get("target")
        if not isinstance(target_id, str) or not target_id:
            raise ESAAError("PLUGIN_SCHEMA_INVALID", f"external file missing target: {path}")

        _, target, input_payload = _load_external_context(root, context_task, target_id)
        prefixes = _runtime_prefixes(target)
        namespace, key = _runtime_parts(path, prefixes)
        contract = _runtime_contract(root, target)
        relative_value = _read_nested(contract, f"{namespace}.{key}")
        if not isinstance(relative_value, str):
            raise ESAAError("PLUGIN_PATH_INVALID", f"runtime uri must resolve to a relative path: {path}")

        target_path = _safe_relative_path(relative_value, path)
        allowed = [str(pattern) for pattern in target.get("allowed_write", [])]
        _validate_allowed_write_patterns(allowed, allow_wildcard, f"external target {target_id}")
        if not allowed or not _matches_any(target_path, allowed):
            raise ESAAError(
                "BOUNDARY_VIOLATION", f"path not allowed for external target {target_id}: {target_path}"
            )
        assert_writable_not_governed(target_path)

        root_input = target.get("root_input")
        if not isinstance(root_input, str) or not root_input:
            raise ESAAError("PLUGIN_SCHEMA_INVALID", f"external target missing root_input: {target_id}")
        target_root = _target_root(root, input_payload, root_input, external_policy)
        absolute_path = _resolve_under_root(target_root, target_path, path)

        out = dict(item)
        out.update(
            {
                "path": path,
                "_esaa_effect_scope": "external",
                "_esaa_source_path": path,
                "_esaa_target": target_id,
                "_esaa_target_root": str(target_root),
                "_esaa_target_path": target_path,
                "_esaa_final_abs_path": str(absolute_path),
            }
        )
        resolved.append(out)
    return resolved
