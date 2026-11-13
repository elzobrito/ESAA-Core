"""Quarantine one syntactically malformed final JSONL line, preserving its bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import EVENT_STORE_PATH
from .durable_io import atomic_write_bytes
from .errors import CorruptedStoreError, ESAAError
from .file_effects import assert_confined_destination
from .project_profile import project_profile_view
from .projection_check import compare_projections
from .projector import materialize
from .runtime_policy import require_operator_runner
from .store_runtime import (
    JSONL_REPAIR_HINT,
    _acquire_store_lock,
    _release_store_lock,
    load_project_profile,
    parse_event_store_text,
    save_issues,
    save_lessons,
    save_project_profile,
    save_roadmap,
)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptedStoreError("JSONL_INVALID", f"invalid UTF-8: {exc}; {JSONL_REPAIR_HINT}") from exc


def _inspect(root: Path, data: bytes) -> tuple[bytes, bytes, list[dict[str, Any]]]:
    lines = data.splitlines(keepends=True)
    if lines:
        try:
            json.loads(lines[-1].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Blank lines are tolerated by the parser, not quarantined. If an
            # earlier line is broken, validate the full log and fail unchanged.
            if lines[-1].strip():
                prefix = b"".join(lines[:-1])
                events = parse_event_store_text(root, _decode(prefix))
                return prefix, lines[-1], events
    return data, b"", parse_event_store_text(root, _decode(data))


def _repair_locked(root: Path, path: Path, *, dry_run: bool) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ESAAError("EVENT_STORE_MISSING", "workspace is not initialized; no files were created") from exc
    prefix, fragment, events = _inspect(root, data)
    # Replay and profile validation happen before any backup or truncation, so
    # valid JSON with bad event semantics cannot be discarded as a torn write.
    roadmap, issues, lessons = materialize(events)
    profile = project_profile_view(events)
    result = {
        "status": "dry_run" if dry_run else ("repaired" if fragment else "unchanged"),
        "repair_needed": bool(fragment),
        "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
        "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
        "truncated_bytes": len(fragment),
    }
    if not fragment:
        compared = compare_projections(
            root,
            {"roadmap.json": roadmap, "issues.json": issues, "lessons.json": lessons},
            ignore_updated_at=not events,
        )
        try:
            profile_matches = load_project_profile(root) == profile
        except (ValueError, OSError):
            profile_matches = False
        result["verify_status"] = "ok" if not compared["divergent"] and profile_matches else "mismatch"
        return result
    backup = f".roadmap/backups/tail-{uuid4().hex}.txt"
    # Validate every destination before the first write (including symlinks).
    destinations = [
        backup,
        EVENT_STORE_PATH,
        ".roadmap/roadmap.json",
        ".roadmap/issues.json",
        ".roadmap/lessons.json",
        ".roadmap/project_profile.json",
    ]
    for relative in destinations:
        assert_confined_destination(root, relative)
    result["backup_path"] = backup
    if dry_run:
        result["verify_status"] = "ok"  # the proposed prefix was fully authenticated and replayed
        return result
    atomic_write_bytes(root / backup, fragment)
    atomic_write_bytes(path, prefix)
    save_roadmap(root, roadmap)
    save_issues(root, issues)
    save_lessons(root, lessons)
    save_project_profile(root, profile)
    from .service import ESAAService

    verification = ESAAService(root).verify()
    result.update(verification)
    return result


def repair_event_store(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Only the malformed final physical line is repairable; all other faults fail closed."""
    require_operator_runner(root, "store repair")
    path = root / EVENT_STORE_PATH
    if not path.is_file():
        raise ESAAError("EVENT_STORE_MISSING", "workspace is not initialized; no files were created")
    assert_confined_destination(root, EVENT_STORE_PATH)
    if dry_run:
        return _repair_locked(root, path, dry_run=True)
    lock = _acquire_store_lock(path, timeout=30.0)
    try:
        return _repair_locked(root, path, dry_run=False)
    finally:
        _release_store_lock(lock)
