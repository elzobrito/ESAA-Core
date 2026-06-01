from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .projector import materialize
from .store import load_roadmap, parse_event_store
from .utils import ensure_parent, sha256_hex, utc_now_iso


def _snapshot_paths(before: int) -> dict[str, Path]:
    base = Path(".roadmap") / "snapshots"
    return {
        "snapshot": base / f"seq-{before:08d}.json",
        "archive": base / f"seq-{before:08d}.events.jsonl",
        "tail": base / f"seq-{before:08d}.tail.jsonl",
        "manifest": base / f"seq-{before:08d}.manifest.json",
    }


def _verify_projection_ok(root: Path, events: list[dict[str, Any]]) -> str:
    stored = load_roadmap(root)
    if not stored:
        raise ESAAError("VERIFY_NOT_OK", "roadmap projection is missing")
    if stored.get("meta", {}).get("run", {}).get("verify_status") != "ok":
        raise ESAAError("VERIFY_NOT_OK", "stored roadmap verify_status is not ok")
    projected, _, _ = materialize(events)
    projected_hash = projected["meta"]["run"]["projection_hash_sha256"]
    if stored.get("meta", {}).get("run", {}).get("projection_hash_sha256") != projected_hash:
        raise ESAAError("VERIFY_NOT_OK", "stored roadmap projection hash does not match replay")
    return projected_hash


def _last_verify_ok_seq(events: list[dict[str, Any]]) -> int:
    seqs = [event["event_seq"] for event in events if event["action"] == "verify.ok"]
    return max(seqs) if seqs else 0


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )


def create_snapshot(root: Path, before: int, compact: bool = False, dry_run: bool = False) -> dict[str, Any]:
    events = parse_event_store(root)
    selected = [event for event in events if int(event["event_seq"]) <= before]
    roadmap, issues, lessons = materialize(selected)

    snapshot = {
        "snapshot": {
            "created_at": utc_now_iso(),
            "before_event_seq": before,
            "events_included": len(selected),
            "compact_artifact": bool(compact),
        },
        "roadmap": roadmap,
        "issues": issues,
        "lessons": lessons,
    }
    snapshot["snapshot"]["snapshot_hash_sha256"] = sha256_hex(snapshot)

    paths = _snapshot_paths(before)
    rel_path = paths["snapshot"]
    path = root / rel_path
    if not dry_run:
        _write_json(path, snapshot)

    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "snapshot",
        "snapshot_path": rel_path.as_posix(),
        "before_event_seq": before,
        "events_included": len(selected),
        "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
        "snapshot_hash_sha256": snapshot["snapshot"]["snapshot_hash_sha256"],
    }

    if compact:
        archive_rel = paths["archive"]
        archive_path = root / archive_rel
        if not dry_run:
            _write_jsonl(archive_path, selected)
        result["compacted_events_path"] = archive_rel.as_posix()
    return result


def compact_event_store(root: Path, before: int, dry_run: bool = True) -> dict[str, Any]:
    events = parse_event_store(root)
    full_projection_hash = _verify_projection_ok(root, events)
    last_verify_ok = _last_verify_ok_seq(events)
    if before > last_verify_ok:
        raise ESAAError("SNAPSHOT_BEFORE_UNVERIFIED", f"before={before} is above last verify.ok seq={last_verify_ok}")

    selected = [event for event in events if int(event["event_seq"]) <= before]
    tail = [event for event in events if int(event["event_seq"]) > before]
    snapshot = create_snapshot(root, before=before, compact=False, dry_run=dry_run)
    paths = _snapshot_paths(before)
    replay_hash = materialize(selected + tail)[0]["meta"]["run"]["projection_hash_sha256"]
    manifest = {
        "created_at": utc_now_iso(),
        "before_event_seq": before,
        "events_archived": len(selected),
        "tail_events": len(tail),
        "snapshot_path": paths["snapshot"].as_posix(),
        "archive_path": paths["archive"].as_posix(),
        "tail_path": paths["tail"].as_posix(),
        "full_projection_hash_sha256": full_projection_hash,
        "replay_projection_hash_sha256": replay_hash,
        "last_verify_ok_event_seq": last_verify_ok,
        "live_event_store_rewritten": False,
    }
    manifest["manifest_hash_sha256"] = sha256_hex(manifest)

    if not dry_run:
        _write_jsonl(root / paths["archive"], selected)
        _write_jsonl(root / paths["tail"], tail)
        _write_json(root / paths["manifest"], manifest)

    return {
        "status": "dry_run" if dry_run else "compacted",
        "snapshot_path": snapshot["snapshot_path"],
        "archive_path": paths["archive"].as_posix(),
        "tail_path": paths["tail"].as_posix(),
        "manifest_path": paths["manifest"].as_posix(),
        "before_event_seq": before,
        "events_archived": len(selected),
        "tail_events": len(tail),
        "full_projection_hash_sha256": full_projection_hash,
        "replay_projection_hash_sha256": replay_hash,
    }


def replay_compacted(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    archive_path = root / manifest["archive_path"]
    tail_path = root / manifest["tail_path"]
    if not archive_path.exists():
        raise ESAAError("SNAPSHOT_ARCHIVE_MISSING", f"archive missing: {archive_path}")
    if not tail_path.exists():
        raise ESAAError("SNAPSHOT_TAIL_MISSING", f"tail missing: {tail_path}")

    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    events = read_jsonl(archive_path) + read_jsonl(tail_path)
    roadmap, _, _ = materialize(events)
    return {
        "events_replayed": len(events),
        "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
        "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
    }
