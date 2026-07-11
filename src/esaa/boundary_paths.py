from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from .errors import ESAAError
from .utils import normalize_rel_path

GOVERNED_STATE_EXACT = frozenset(
    {
        ".roadmap/activity.jsonl",
        ".roadmap/roadmap.json",
        ".roadmap/issues.json",
        ".roadmap/lessons.json",
    }
)

_GOVERNED_STATE_PROBE_PATHS = (
    ".roadmap",
    ".roadmap/activity.jsonl",
    ".roadmap/roadmap.json",
    ".roadmap/issues.json",
    ".roadmap/lessons.json",
    ".roadmap/evil.json",
)


def is_governed_state_path(path: str) -> bool:
    norm = normalize_rel_path(path)
    return norm == ".roadmap" or norm.startswith(".roadmap/")


def pattern_targets_governed_state(pattern: str) -> bool:
    norm = normalize_rel_path(pattern)
    if is_governed_state_path(norm):
        return True
    return any(fnmatch.fnmatch(probe, norm) for probe in _GOVERNED_STATE_PROBE_PATHS)


def assert_writable_not_governed(path: str) -> None:
    if is_governed_state_path(path):
        raise ESAAError("BOUNDARY_VIOLATION", f"path targets governed ESAA state: {path}")


def path_within_scope(path: str, scope: str) -> bool:
    norm_path = normalize_rel_path(path)
    norm_scope = normalize_rel_path(scope)
    if any(part == ".." for part in PurePosixPath(norm_path).parts):
        return False
    if norm_scope.endswith("/"):
        scope_parts = PurePosixPath(norm_scope.rstrip("/")).parts
        path_parts = PurePosixPath(norm_path).parts
        if len(path_parts) < len(scope_parts):
            return False
        return path_parts[: len(scope_parts)] == scope_parts
    return norm_path == norm_scope


def validate_hotfix_scope_entries(scopes: list[str]) -> list[str]:
    if not scopes:
        raise ESAAError("HOTFIX_SCOPE_INVALID", "scope_patch ausente ou vazio")

    validated: list[str] = []
    for raw in scopes:
        if not isinstance(raw, str) or not raw.strip():
            raise ESAAError("HOTFIX_SCOPE_INVALID", "scope_patch entry must be non-empty")
        norm = normalize_rel_path(raw.strip())
        if any(part == ".." for part in PurePosixPath(norm).parts):
            raise ESAAError("HOTFIX_SCOPE_INVALID", f"scope_patch forbids traversal: {raw}")
        if not norm.endswith("/"):
            last = PurePosixPath(norm).name
            if "." not in last:
                raise ESAAError("HOTFIX_SCOPE_INVALID", f"directory scope must end with '/': {raw}")
        validated.append(norm)
    return validated