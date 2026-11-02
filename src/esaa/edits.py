from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ESAAError
from .utils import normalize_rel_path

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _workspace_path(path: str) -> str:
    if path.startswith("runtime://"):
        raise ESAAError("EDIT_INVALID", "edit updates are not supported for runtime:// file_updates")
    raw = path.replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("..") or ":" in PurePosixPath(raw).parts[0]:
        raise ESAAError("EDIT_INVALID", f"invalid edit path: {path}")
    norm = normalize_rel_path(raw)
    if not norm or any(part == ".." for part in PurePosixPath(norm).parts):
        raise ESAAError("EDIT_INVALID", f"path traversal forbidden for edit update: {path}")
    return norm


def _validate_edit_item(item: dict[str, Any], path: str) -> None:
    old = item.get("old_string")
    new = item.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        raise ESAAError("EDIT_INVALID", f"{path}: old_string and new_string must be strings")
    if old == "":
        raise ESAAError("EDIT_INVALID", f"{path}: old_string must not be empty")
    if old == new:
        raise ESAAError("EDIT_INVALID", f"{path}: old_string and new_string must differ")
    if "replace_all" in item and not isinstance(item["replace_all"], bool):
        raise ESAAError("EDIT_INVALID", f"{path}: replace_all must be boolean")


def apply_edits(text: str, edits: list[dict[str, Any]], path: str) -> str:
    if not edits:
        raise ESAAError("EDIT_INVALID", f"{path}: edits must contain at least one item")
    current = text
    for edit in edits:
        _validate_edit_item(edit, path)
        old = edit["old_string"]
        new = edit["new_string"]
        count = current.count(old)
        if count == 0:
            raise ESAAError("EDIT_TARGET_NOT_FOUND", f"{path}: old_string not found")
        if count > 1 and not edit.get("replace_all", False):
            raise ESAAError("EDIT_AMBIGUOUS", f"{path}: old_string matched {count} times")
        current = (
            current.replace(old, new) if edit.get("replace_all", False) else current.replace(old, new, 1)
        )
    return current


def resolve_edit_updates(root: Path, file_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for item in file_updates:
        if "binary" in item:
            if "content" in item or "edits" in item:
                raise ESAAError("SCHEMA_INVALID", "binary update cannot contain text or edits")
            resolved.append(dict(item))
            continue
        if "edits" not in item:
            if "content" not in item:
                raise ESAAError(
                    "SCHEMA_INVALID", f"file_update requires content or edits: {item.get('path')}"
                )
            resolved.append(dict(item))
            continue
        if "content" in item:
            raise ESAAError("EDIT_INVALID", "file_update cannot include both content and edits")
        path = _workspace_path(str(item.get("path", "")))
        base_sha = item.get("base_sha256")
        edits = item.get("edits")
        if not isinstance(base_sha, str) or not _SHA256_RE.fullmatch(base_sha):
            raise ESAAError("EDIT_INVALID", f"{path}: base_sha256 must be 64 lowercase hex characters")
        if not isinstance(edits, list) or not edits:
            raise ESAAError("EDIT_INVALID", f"{path}: edits must be a non-empty list")

        target = root / path
        try:
            before_bytes = target.read_bytes()
        except FileNotFoundError as exc:
            raise ESAAError(
                "EDIT_BASE_MISMATCH", f"{path}: file does not exist; expected base_sha256={base_sha}"
            ) from exc
        actual_sha = hashlib.sha256(before_bytes).hexdigest()
        if actual_sha != base_sha:
            raise ESAAError(
                "EDIT_BASE_MISMATCH",
                f"{path}: base_sha256 mismatch expected={base_sha} actual={actual_sha}",
            )
        try:
            before_text = before_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ESAAError("EDIT_INVALID", f"{path}: target file is not valid UTF-8") from exc

        after_text = apply_edits(before_text, edits, path)
        resolved.append({"path": path, "content": after_text})
    return resolved
