from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .errors import ESAAError
from .provenance import resolve_runner
from .utils import ensure_parent

COMMAND_INPUT_REL_DIR = Path(".roadmap") / "runner-inputs" / "commands"
_RUNNER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _commands_dir(root: Path) -> Path:
    return root / COMMAND_INPUT_REL_DIR


def _runner_id(value: str | None = None) -> str:
    runner_id = (value or resolve_runner()["runner_id"] or "").strip()
    if not runner_id or not _RUNNER_ID_RE.fullmatch(runner_id):
        raise ESAAError("RUNNER_INVALID", "runner_id must contain only letters, digits, dot, underscore, or dash")
    return runner_id


def _runner_path(root: Path, runner_id: str) -> Path:
    return _commands_dir(root) / f"{runner_id}.yaml"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ESAAError("INPUT_NOT_FOUND", f"commands input file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ESAAError("INPUT_INVALID", "commands input must be a YAML mapping")
    return loaded


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})


def _ordered_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            out.append(cleaned)
            seen.add(cleaned)
    return out


def _available_surfaces(profile: dict[str, Any]) -> list[str]:
    surfaces = profile.get("command_surfaces") or {}
    if not isinstance(surfaces, dict):
        raise ESAAError("INPUT_INVALID", "command_surfaces must be a mapping when present")
    names: list[str] = []
    for name, details in surfaces.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(details, dict) and details.get("available") is False:
            continue
        names.append(name.strip())
    return sorted(set(names))


def _available_tools(profile: dict[str, Any]) -> list[str]:
    tools: set[str] = set(_string_list(profile.get("available_tools")))
    grouped = profile.get("windows_path_tools") or {}
    if isinstance(grouped, dict):
        for values in grouped.values():
            tools.update(_string_list(values))
    elif grouped:
        raise ESAAError("INPUT_INVALID", "windows_path_tools must be a mapping when present")
    return sorted(tools)


def _wsl_tools(profile: dict[str, Any]) -> list[str]:
    surfaces = profile.get("command_surfaces") or {}
    tools: set[str] = set()
    if not isinstance(surfaces, dict):
        return []
    for name, details in surfaces.items():
        if not isinstance(name, str) or "wsl" not in name.lower() or not isinstance(details, dict):
            continue
        verified = details.get("verified_tools") or {}
        if isinstance(verified, dict):
            tools.update(key for key in verified if isinstance(key, str) and key.strip())
        elif verified:
            raise ESAAError("INPUT_INVALID", f"command_surfaces.{name}.verified_tools must be a mapping")
    return sorted(tools)


def summarize_commands_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_surfaces": _available_surfaces(profile),
        "available_tools": _available_tools(profile),
        "wsl_tools": _wsl_tools(profile),
        "recommended_agent_rules": _ordered_string_list(profile.get("recommended_agent_rules")),
    }


def validate_commands_input(path: Path) -> dict[str, Any]:
    profile = _read_yaml(path)
    return {
        "status": "valid",
        "input_type": "commands",
        "path": str(path),
        "summary": summarize_commands_profile(profile),
    }


def register_commands_input(root: Path, path: Path, runner_id: str | None = None) -> dict[str, Any]:
    resolved_runner = _runner_id(runner_id)
    profile = _read_yaml(path)
    summary = summarize_commands_profile(profile)
    dest = _runner_path(root, resolved_runner)
    ensure_parent(dest)
    dest.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "status": "registered",
        "input_type": "commands",
        "runner_id": resolved_runner,
        "path": _relative(dest, root),
        "summary": summary,
    }


def show_commands_input(root: Path, runner_id: str | None = None) -> dict[str, Any]:
    resolved_runner = _runner_id(runner_id)
    path = _runner_path(root, resolved_runner)
    if not path.exists():
        return {
            "status": "missing",
            "input_type": "commands",
            "runner_id": resolved_runner,
            "path": _relative(path, root),
        }
    profile = _read_yaml(path)
    return {
        "status": "registered",
        "input_type": "commands",
        "runner_id": resolved_runner,
        "path": _relative(path, root),
        "summary": summarize_commands_profile(profile),
    }


def load_runtime_capabilities(root: Path, runner_id: str | None = None) -> dict[str, Any] | None:
    shown = show_commands_input(root, runner_id)
    if shown["status"] != "registered":
        return None
    summary = dict(shown["summary"])
    return {
        "runner_id": shown["runner_id"],
        "command_surfaces": summary["command_surfaces"],
        "available_tools": summary["available_tools"],
        "wsl_tools": summary["wsl_tools"],
        "recommended_agent_rules": summary["recommended_agent_rules"],
    }
