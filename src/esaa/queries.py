"""Read-only task and event queries; never trust or rewrite cached projections."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .projector import materialize
from .seeds import tasks_with_planned_plugins
from .store import parse_event_store
from .utils import sha256_hex


def _events(root: Path) -> list[dict[str, Any]]:
    if not (root / ".roadmap/activity.jsonl").is_file():
        raise ESAAError("EVENT_STORE_MISSING", "workspace is not initialized; no files were created")
    return parse_event_store(root)


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ESAAError("INVALID_ARGUMENT", "limit must be between 1 and 1000")
    return value


def list_tasks(
    root: Path,
    *,
    statuses: list[str] | None = None,
    kind: str | None = None,
    assigned_to: str | None = None,
    source: str = "all",
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    _limit(limit)
    if source not in {"all", "event_store", "planned"}:
        raise ESAAError("INVALID_ARGUMENT", "invalid task source")
    if set(statuses or []) - {"todo", "in_progress", "review", "done"} or kind not in {
        None,
        "spec",
        "impl",
        "qa",
    }:
        raise ESAAError("INVALID_ARGUMENT", "invalid task status or kind")
    events = _events(root)
    roadmap, _, _ = materialize(events)
    tasks, sources = tasks_with_planned_plugins(root, roadmap["tasks"])
    seq = events[-1]["event_seq"] if events else 0
    filters = {
        "status": sorted(set(statuses or [])),
        "kind": kind,
        "assigned_to": assigned_to,
        "source": source,
    }
    fingerprint = sha256_hex({"tasks": tasks, "sources": sources, "seq": seq, "filters": filters})
    after = ""
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            if (
                not isinstance(token, dict)
                or set(token) != {"fingerprint", "after"}
                or not isinstance(token["after"], str)
            ):
                raise ValueError("invalid shape")
        except (ValueError, UnicodeError, TypeError) as exc:
            raise ESAAError("INVALID_ARGUMENT", "invalid task cursor") from exc
        if token["fingerprint"] != fingerprint:
            raise ESAAError("QUERY_CURSOR_STALE", "task query changed; start again without cursor")
        after = token["after"]
    rows = [
        dict(task, source=sources[task["task_id"]])
        for task in sorted(tasks, key=lambda t: t["task_id"])
        if (not statuses or task["status"] in statuses)
        and (kind is None or task["task_kind"] == kind)
        and (assigned_to is None or task.get("assigned_to") == assigned_to)
        and (
            source == "all"
            or (source == "planned" and sources[task["task_id"]] != "event_store")
            or sources[task["task_id"]] == source
        )
    ]
    remaining = [row for row in rows if row["task_id"] > after]
    page = remaining[:limit]
    next_cursor = None
    if len(remaining) > limit:
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"fingerprint": fingerprint, "after": page[-1]["task_id"]}).encode()
        ).decode()
    return {
        "tasks": page,
        "total": len(rows),
        "filters": filters,
        "next_cursor": next_cursor,
        "last_event_seq": seq,
    }


def list_activity(
    root: Path,
    *,
    task_id: str | None = None,
    actions: list[str] | None = None,
    exclude_actions: list[str] | None = None,
    hide_verify: bool = False,
    after_seq: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    _limit(limit)
    if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
        raise ESAAError("INVALID_ARGUMENT", "after-seq must be a non-negative integer")
    events = _events(root)
    rows = [
        event
        for event in events
        if event["event_seq"] > after_seq
        and (task_id is None or event["payload"].get("task_id") == task_id)
        and (not actions or event["action"] in actions)
        and event["action"] not in (exclude_actions or [])
        and not (hide_verify and event["action"].startswith("verify."))
    ]
    page = rows[:limit]
    return {
        "events": page,
        "filters": {
            "task_id": task_id,
            "actions": actions or [],
            "exclude_actions": exclude_actions or [],
            "hide_verify": hide_verify,
        },
        "next_after_seq": page[-1]["event_seq"] if page else after_seq,
        "has_more": len(rows) > limit,
        "last_event_seq": events[-1]["event_seq"] if events else 0,
    }


def format_query(result: dict[str, Any], output_format: str) -> str:
    rows = result.get("tasks", result.get("events", []))
    if output_format == "jsonl":
        return "\n".join(json.dumps(row, ensure_ascii=True) for row in rows)
    if output_format == "table":
        columns = (
            ["task_id", "status", "task_kind", "assigned_to", "source", "title"]
            if "tasks" in result
            else ["event_seq", "action", "actor", "task_id"]
        )

        def value(row, key):
            item = (
                row.get("payload", {}).get(key, "")
                if key == "task_id" and "payload" in row
                else row.get(key, "")
            )
            return "".join(c if c.isprintable() else " " for c in str(item))

        return "\n".join(
            ["\t".join(columns)] + ["\t".join(value(row, key) for key in columns) for row in rows]
        )
    return json.dumps(result, ensure_ascii=True, indent=2)
