from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import PROJECTOR_VERSION, SCHEMA_VERSION
from .errors import CorruptedStoreError, ESAAError
from .project_profile import project_profile_view
from .projector import apply_events, materialize, replay_state, restore_state, serialize_state
from .store_runtime import (
    append_transactional,
    load_roadmap,
    next_event_seq,
    parse_event_store,
    parse_event_store_tail,
    read_event_at_offset,
    scan_event_offsets,
)
from .utils import ensure_parent, sha256_hex, utc_now_iso
from .verify_annotations import chain_status, ts_regression_warning

SNAPSHOT_FORMAT_VERSION = "2"


@dataclass
class VerifiedReplay:
    used_snapshot: bool
    state: dict[str, Any]
    full_events: list[dict[str, Any]] | None
    tail_events: list[dict[str, Any]]
    effective_events: list[dict[str, Any]]
    project_profile: dict[str, Any] | None
    prefix_chain_status: str
    prefix_ts_regression: dict[str, Any] | None
    last_covered_event_ts: str | None
    completed_ts_by_task: dict[str, dict[str, str]]
    has_actor_events: bool
    has_verification_events: bool


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


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )


def _snapshot_payload_hash(snapshot_doc: dict[str, Any]) -> str:
    meta = snapshot_doc.get("snapshot")
    if isinstance(meta, dict) and "snapshot_hash_sha256" in meta:
        saved = meta.pop("snapshot_hash_sha256")
        try:
            return sha256_hex(snapshot_doc)
        finally:
            meta["snapshot_hash_sha256"] = saved
    return sha256_hex(snapshot_doc)


def create_snapshot(root: Path, before: int, compact: bool = False, dry_run: bool = False) -> dict[str, Any]:
    events = parse_event_store(root)
    last_seq = int(events[-1]["event_seq"]) if events else 0
    if before < 0 or before > last_seq:
        raise ESAAError(
            "SNAPSHOT_BEFORE_UNVERIFIED",
            f"before={before} is outside verified event range 0..{last_seq}",
        )
    selected = [event for event in events if int(event["event_seq"]) <= before]
    state = replay_state(selected)
    roadmap, _, _ = materialize(selected)
    last_covered = selected[-1] if selected else None
    last_covered_offset, tail_offset = scan_event_offsets(root, before)
    last_covered_hash = sha256_hex(last_covered) if last_covered is not None else sha256_hex({})

    completed_ts_by_task = {
        str(e["payload"]["task_id"]): {"ts": str(e["ts"]), "actor": str(e.get("actor", ""))}
        for e in selected
        if e["action"] == "complete" and isinstance(e.get("payload"), dict) and "task_id" in e["payload"]
    }
    rejection_events = [e for e in selected if e["action"] in {"output.rejected", "task.release"}]

    snapshot: dict[str, Any] = {
        "snapshot_format_version": SNAPSHOT_FORMAT_VERSION,
        "snapshot": {
            "created_at": utc_now_iso(),
            "before_event_seq": before,
            "events_included": len(selected),
            "last_covered_event_seq": int(last_covered["event_seq"]) if last_covered is not None else 0,
            "last_covered_event_offset_bytes": last_covered_offset,
            "last_covered_event_hash": last_covered_hash,
            "tail_offset_bytes": tail_offset,
            "projector_version": PROJECTOR_VERSION,
            "compact_artifact": bool(compact),
        },
        "state": serialize_state(state),
        "roadmap": roadmap,
        "prefix_meta": {
            "project_profile": project_profile_view(selected),
            "chain_status": chain_status(selected),
            "ts_regression": ts_regression_warning(selected),
            "last_covered_event_ts": str(last_covered["ts"]) if last_covered is not None else None,
            "has_actor_events": any(e["action"].startswith("actor.") for e in selected),
            "has_verification_events": any(e["action"].startswith("verification.") for e in selected),
            "rejection_events": rejection_events,
            "completed_ts_by_task": completed_ts_by_task,
        },
    }
    snapshot_hash = _snapshot_payload_hash(snapshot)
    snapshot["snapshot"]["snapshot_hash_sha256"] = snapshot_hash

    paths = _snapshot_paths(before)
    rel_path = paths["snapshot"]
    path = root / rel_path
    if not dry_run:

        def build_anchor(current_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seq = next_event_seq(current_events)
            return [
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": f"EV-{seq:08d}",
                    "event_seq": seq,
                    "ts": utc_now_iso(),
                    "actor": "orchestrator",
                    "action": "snapshot.anchor",
                    "payload": {
                        "snapshot_path": rel_path.as_posix(),
                        "before_event_seq": before,
                        "snapshot_hash_sha256": snapshot_hash,
                        "tail_offset_bytes": tail_offset,
                        "last_covered_event_seq": snapshot["snapshot"]["last_covered_event_seq"],
                        "last_covered_event_hash": last_covered_hash,
                        "projector_version": PROJECTOR_VERSION,
                    },
                }
            ]

        append_transactional(root, build_anchor)
        _write_json(path, snapshot)

    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "snapshot",
        "snapshot_format_version": SNAPSHOT_FORMAT_VERSION,
        "snapshot_path": rel_path.as_posix(),
        "before_event_seq": before,
        "events_included": len(selected),
        "tail_offset_bytes": tail_offset,
        "projector_version": PROJECTOR_VERSION,
        "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
        "snapshot_hash_sha256": snapshot_hash,
    }

    if compact:
        archive_rel = paths["archive"]
        archive_path = root / archive_rel
        if not dry_run:
            _write_jsonl(archive_path, selected)
        result["compacted_events_path"] = archive_rel.as_posix()
    return result


def _try_load_snapshot(root: Path, snap_path: Path) -> VerifiedReplay:
    try:
        doc = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable snapshot: {exc}") from exc

    if not isinstance(doc, dict) or doc.get("snapshot_format_version") != SNAPSHOT_FORMAT_VERSION:
        raise ValueError("unsupported snapshot format version")

    meta = doc.get("snapshot")
    state_raw = doc.get("state")
    prefix_meta = doc.get("prefix_meta")
    if not isinstance(meta, dict) or not isinstance(state_raw, dict) or not isinstance(prefix_meta, dict):
        raise ValueError("malformed snapshot structure")

    if meta.get("projector_version") != PROJECTOR_VERSION:
        raise ValueError(
            f"projector_version mismatch: {meta.get('projector_version')} != {PROJECTOR_VERSION}"
        )

    expected_hash = meta.get("snapshot_hash_sha256")
    if not isinstance(expected_hash, str) or _snapshot_payload_hash(doc) != expected_hash:
        raise ValueError("snapshot_hash_sha256 mismatch")

    before_seq = int(meta.get("before_event_seq", -1))
    last_covered_seq = int(meta.get("last_covered_event_seq", -1))
    last_covered_offset = int(meta.get("last_covered_event_offset_bytes", -1))
    tail_offset = int(meta.get("tail_offset_bytes", -1))
    last_covered_hash = meta.get("last_covered_event_hash")
    if before_seq < 0 or last_covered_seq < 0 or last_covered_offset < 0 or tail_offset < 0:
        raise ValueError("invalid snapshot offsets or sequence")

    last_covered_event: dict[str, Any] | None = None
    expected_prev_hash: str | None = None
    if last_covered_seq > 0:
        try:
            last_covered_event, next_offset = read_event_at_offset(root, last_covered_offset)
        except (OSError, CorruptedStoreError) as exc:
            raise ValueError(f"cannot read covered boundary event: {exc}") from exc
        if next_offset != tail_offset:
            raise ValueError(f"tail_offset_bytes mismatch: {next_offset} != {tail_offset}")
        if int(last_covered_event.get("event_seq", -1)) != last_covered_seq:
            raise ValueError(
                f"covered event_seq mismatch: {last_covered_event.get('event_seq')} != {last_covered_seq}"
            )
        if sha256_hex(last_covered_event) != last_covered_hash:
            raise ValueError("last_covered_event_hash mismatch")
        expected_prev_hash = last_covered_event.get("event_hash")

    tail_events = parse_event_store_tail(
        root,
        tail_offset,
        expected_first_seq=before_seq + 1,
        expected_prev_hash=expected_prev_hash,
    )

    anchored = any(
        e["action"] == "snapshot.anchor"
        and isinstance(e.get("payload"), dict)
        and e["payload"].get("snapshot_hash_sha256") == expected_hash
        and e["payload"].get("before_event_seq") == before_seq
        and e["payload"].get("tail_offset_bytes") == tail_offset
        and e["payload"].get("last_covered_event_seq") == last_covered_seq
        and e["payload"].get("last_covered_event_hash") == last_covered_hash
        and e["payload"].get("projector_version") == PROJECTOR_VERSION
        for e in tail_events
    )
    if not anchored:
        raise ValueError("snapshot has no matching snapshot.anchor event in event store")

    state = restore_state(state_raw, copy=False)
    apply_events(state, tail_events)

    rejection_events = list(prefix_meta.get("rejection_events", []))
    effective_events = (
        rejection_events
        + ([last_covered_event] if not tail_events and last_covered_event is not None else [])
        + tail_events
    )

    return VerifiedReplay(
        used_snapshot=True,
        state=state,
        full_events=None,
        tail_events=tail_events,
        effective_events=effective_events,
        project_profile=prefix_meta.get("project_profile"),
        prefix_chain_status=str(prefix_meta.get("chain_status", "unanchored")),
        prefix_ts_regression=prefix_meta.get("ts_regression"),
        last_covered_event_ts=prefix_meta.get("last_covered_event_ts"),
        completed_ts_by_task=dict(prefix_meta.get("completed_ts_by_task", {})),
        has_actor_events=bool(prefix_meta.get("has_actor_events", False)),
        has_verification_events=bool(prefix_meta.get("has_verification_events", False)),
    )


def load_verified_replay(root: Path, *, full: bool = False) -> VerifiedReplay:
    """Load state via latest verified anchored snapshot + tail, or fall back to full replay."""
    if not full:
        snap_dir = root / ".roadmap" / "snapshots"
        if snap_dir.is_dir():
            candidates = sorted(snap_dir.glob("seq-*.json"), reverse=True)
            for snap_path in candidates:
                try:
                    return _try_load_snapshot(root, snap_path)
                except CorruptedStoreError:
                    raise
                except ValueError as exc:
                    print(f"warning: ignoring snapshot {snap_path.name}: {exc}", file=sys.stderr)

    events = parse_event_store(root)
    state = replay_state(events, verify_hashes="all" if full else "auto")
    completed_ts_by_task = {
        str(e["payload"]["task_id"]): {"ts": str(e["ts"]), "actor": str(e.get("actor", ""))}
        for e in events
        if e["action"] == "complete" and isinstance(e.get("payload"), dict) and "task_id" in e["payload"]
    }
    return VerifiedReplay(
        used_snapshot=False,
        state=state,
        full_events=events,
        tail_events=events,
        effective_events=events,
        project_profile=project_profile_view(events),
        prefix_chain_status="unanchored",
        prefix_ts_regression=None,
        last_covered_event_ts=None,
        completed_ts_by_task=completed_ts_by_task,
        has_actor_events=any(e["action"].startswith("actor.") for e in events),
        has_verification_events=any(e["action"].startswith("verification.") for e in events),
    )


def compact_event_store(root: Path, before: int, dry_run: bool = True) -> dict[str, Any]:
    events = parse_event_store(root)
    full_projection_hash = _verify_projection_ok(root, events)
    last_seq = int(events[-1]["event_seq"]) if events else 0
    if before < 0 or before > last_seq:
        raise ESAAError(
            "SNAPSHOT_BEFORE_UNVERIFIED", f"before={before} is above last verified seq={last_seq}"
        )

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
        "last_verified_event_seq": last_seq,
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
