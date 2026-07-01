from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CorruptedStoreError, ESAAError
from .events import make_event
from .projector import materialize
from .seeds import BASELINE_LESSONS
from .store import append_events, ensure_event_store, parse_event_store, save_issues, save_lessons, save_roadmap
from .utils import ensure_parent


def plan_activity_clear(root: Path, *, force: bool, dry_run: bool, backup_dir: str) -> dict[str, Any]:
    if not force:
        raise ESAAError("CLEAR_REQUIRES_FORCE", "activity clear requires --force")

    path = ensure_event_store(root)
    raw = path.read_text(encoding="utf-8")
    raw_lines = [line for line in raw.splitlines() if line.strip()]
    parse_error: dict[str, str] | None = None
    try:
        events_removed = len(parse_event_store(root))
    except CorruptedStoreError as exc:
        events_removed = len(raw_lines)
        parse_error = {"error_code": exc.code, "error_message": exc.message}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_base = Path(backup_dir)
    backup_name = f"activity-{stamp}.jsonl"
    if backup_base.is_absolute():
        backup_path = backup_base / backup_name
        backup_report = str(backup_path)
    else:
        backup_path = root / backup_base / backup_name
        backup_report = str(backup_base / backup_name).replace("\\", "/")

    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "cleared",
        "event_store": ".roadmap/activity.jsonl",
        "events_removed": events_removed,
        "bytes_removed": len(raw.encode("utf-8")),
        "backup_path": backup_report,
        "_backup_path": backup_path,
        "_raw": raw,
    }
    if parse_error:
        result["parse_error_before_clear"] = parse_error
    return result


def apply_activity_clear(root: Path, plan: dict[str, Any]) -> None:
    backup_path = plan.pop("_backup_path")
    raw = plan.pop("_raw")
    ensure_parent(backup_path)
    backup_path.write_text(raw, encoding="utf-8")

    seed_events = [
        make_event(
            1,
            actor="orchestrator",
            action="orchestrator.view.mutate",
            payload={"target": "lessons", "change": "baseline_reseed", "lessons": BASELINE_LESSONS},
        ),
        make_event(2, actor="orchestrator", action="verify.start", payload={"strict": True}),
    ]
    preview_roadmap, _, _ = materialize(seed_events)
    seed_events.append(
        make_event(
            3,
            actor="orchestrator",
            action="verify.ok",
            payload={"projection_hash_sha256": preview_roadmap["meta"]["run"]["projection_hash_sha256"]},
        )
    )

    ensure_event_store(root).write_text("", encoding="utf-8")
    append_events(root, seed_events)
    roadmap, issues, lessons = materialize(seed_events)
    save_roadmap(root, roadmap)
    save_issues(root, issues)
    save_lessons(root, lessons)
