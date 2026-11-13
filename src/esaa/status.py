"""Read-only workspace summary from one event-store snapshot."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution import build_eligibility
from .projector import finalize_views, materialize
from .seeds import tasks_with_planned_plugins
from .snapshot import load_verified_replay
from .store_runtime import load_roadmap, parse_event_store
from .verify_annotations import chain_status

_STATUSES = ("todo", "in_progress", "review", "done")
_SEVERITIES = ("critical", "high", "medium", "low")


def _age_seconds(value: Any, now: datetime, *, clamp: bool = True) -> float | None:
    try:
        started = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        seconds = (now - started).total_seconds()
        return max(0.0, seconds) if clamp else seconds
    except (ValueError, TypeError):
        return None


def build_status(root: Path, now: datetime | None = None) -> dict[str, Any]:
    """Summarize authoritative events without locking or refreshing disk projections.

    ``verify_status`` is the latest recorded verification result. Projection
    freshness is reported separately, without running a new verification.
    """
    now = now if now is not None else datetime.now(UTC)
    snap_dir = root / ".roadmap" / "snapshots"
    if snap_dir.is_dir() and any(snap_dir.glob("seq-*.json")):
        replay = load_verified_replay(root)
        roadmap, issues_view, _ = finalize_views(replay.state)
        events = replay.effective_events
        completed_ts = dict(replay.completed_ts_by_task)
        for event in replay.tail_events:
            if event["action"] == "complete":
                completed_ts[str(event["payload"]["task_id"])] = {
                    "ts": str(event["ts"]),
                    "actor": str(event.get("actor", "")),
                }
        prefix_chain = replay.prefix_chain_status
        _ = prefix_chain
    else:
        events = parse_event_store(root)
        roadmap, issues_view, _ = materialize(events)
        completed_ts = {
            str(e["payload"]["task_id"]): {"ts": str(e["ts"]), "actor": str(e.get("actor", ""))}
            for e in events
            if e["action"] == "complete" and isinstance(e.get("payload"), dict) and "task_id" in e["payload"]
        }
        prefix_chain = "unanchored"
        _ = prefix_chain
    run = roadmap["meta"]["run"]
    task_view = tasks_with_planned_plugins(root, roadmap["tasks"])
    tasks, _ = task_view
    eligibility = build_eligibility(root, events, roadmap, now=now, task_view=task_view)
    stored = load_roadmap(root) or {}
    stored_seq = stored.get("meta", {}).get("run", {}).get("last_event_seq")
    review_queue = []
    for task in tasks:
        if task["status"] != "review":
            continue
        comp_info = completed_ts.get(task["task_id"], {})
        completed_at = comp_info.get("ts")
        review_queue.append(
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "completed_by": comp_info.get("actor") or None,
                "completed_at": completed_at,
                "waiting_seconds": _age_seconds(completed_at, now),
            }
        )

    def review_order(row: dict[str, Any]) -> tuple[bool, float, str]:
        # Clock skew can put completions ahead of now. Keep their chronological
        # order while displaying a nonnegative waiting time.
        age = _age_seconds(row["completed_at"], now, clamp=False)
        return age is None, -(age or 0), row["task_id"]

    review_queue.sort(key=review_order)
    issues = [issue for issue in issues_view["issues"] if issue["status"] != "resolved"]
    issues.sort(
        key=lambda issue: (
            _SEVERITIES.index(issue["severity"]) if issue["severity"] in _SEVERITIES else len(_SEVERITIES),
            issue["issue_id"],
        )
    )
    issue_counts = Counter(issue["severity"] for issue in issues)
    task_counts = Counter(task["status"] for task in tasks)
    return {
        "last_event_seq": run["last_event_seq"],
        "verify_status": run["verify_status"],
        "chain_status": chain_status(events),
        "projections_stale": stored_seq != run["last_event_seq"],
        "tasks_by_status": {key: task_counts[key] for key in _STATUSES},
        "review_queue": review_queue,
        "eligible": [{key: task[key] for key in ("task_id", "title")} for task in eligibility["eligible"]],
        "stale_claims": [
            {**claim, "age_seconds": _age_seconds(claim["started_at"], now)}
            for claim in eligibility["stale_claims"]
        ],
        "open_issues_by_severity": {key: issue_counts[key] for key in _SEVERITIES},
        "open_issues": [
            {key: issue[key] for key in ("issue_id", "severity", "title")} for issue in issues[:10]
        ],
    }


def _line(value: Any) -> str:
    text = "".join(char if char.isprintable() else " " for char in str(value))
    widths = [2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text]
    if sum(widths) <= 100:
        return text
    columns = 0
    end = 0
    for width in widths:
        if columns + width > 97:
            break
        columns += width
        end += 1
    return text[:end] + "..."


def render_status_table(status: dict[str, Any]) -> str:
    """Render at most 40 plain-text lines, each at most 100 columns."""
    lines = [
        _line(
            f"ESAA status | seq {status['last_event_seq']} | verify {status['verify_status']}"
            f" | chain {status['chain_status']} | projections stale: {status['projections_stale']}"
        ),
        _line("Tasks: " + " | ".join(f"{key} {value}" for key, value in status["tasks_by_status"].items())),
        _line(
            "Open issues: "
            + " | ".join(f"{key} {value}" for key, value in status["open_issues_by_severity"].items())
        ),
    ]
    # Fixed section budgets preserve visibility of every list under heavy load.
    sections = (
        ("Review queue (oldest first)", status["review_queue"], 9),
        ("Eligible", status["eligible"], 8),
        ("Stale claims", status["stale_claims"], 8),
        ("Open issues (up to 10 most severe)", status["open_issues"], 8),
    )
    for title, rows, budget in sections:
        lines.append(title + ":")
        if not rows:
            lines.append("  (none)")
            continue
        visible = budget if len(rows) <= budget else budget - 1
        for row in rows[:visible]:
            if "waiting_seconds" in row:
                detail = (
                    f"{row['completed_by']} | {row['completed_at']} | waiting {row['waiting_seconds']}s"
                    f" | {row['title']}"
                )
            elif "age_seconds" in row:
                detail = f"{row['assigned_to']} | {row['started_at']} | age {row['age_seconds']}s"
            elif "severity" in row:
                detail = f"{row['severity']} | {row['title']}"
            else:
                detail = row["title"]
            lines.append(_line(f"  {row.get('task_id', row.get('issue_id'))} | {detail}"))
        if len(rows) > visible:
            lines.append(f"  (+{len(rows) - visible} mais)")
    return "\n".join(lines)


def status_command(root: Path, output_format: str) -> int:
    """CLI entry point, keeping summary and presentation logic out of the parser."""
    status = build_status(root)
    print(
        json.dumps(status, ensure_ascii=True, indent=2)
        if output_format == "json"
        else render_status_table(status)
    )
    return 2 if status["verify_status"] in {"mismatch", "corrupted"} else 0
