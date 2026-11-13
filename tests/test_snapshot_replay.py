"""Tests for anchored v2 snapshot replay, fallback safety, and performance (AUD-O2-040)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from esaa.cli import main
from esaa.constants import SCHEMA_VERSION
from esaa.errors import ESAAError
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.snapshot import compact_event_store, create_snapshot, load_verified_replay
from esaa.store import parse_event_store


def _make_synthetic_store(root: Path, num_tasks: int) -> None:
    ESAAService(root).init()
    base_events = parse_event_store(root)
    seq = len(base_events) + 1
    lines: list[str] = []
    for i in range(1, num_tasks + 1):
        tid = f"SYN-{i:06d}"
        ts = f"2099-01-01T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z"
        events = [
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"EV-{seq:08d}",
                "event_seq": seq,
                "ts": ts,
                "actor": "orchestrator",
                "action": "task.create",
                "payload": {
                    "task_id": tid,
                    "task_kind": "impl",
                    "title": f"Task {tid}",
                    "description": f"Synthetic task {tid}",
                    "outputs": {"files": [f"src/mod_{i}.py"]},
                },
            },
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"EV-{seq + 1:08d}",
                "event_seq": seq + 1,
                "ts": ts,
                "actor": "agent-impl",
                "action": "claim",
                "payload": {"task_id": tid, "prior_status": "todo"},
            },
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"EV-{seq + 2:08d}",
                "event_seq": seq + 2,
                "ts": ts,
                "actor": "agent-impl",
                "action": "complete",
                "payload": {
                    "task_id": tid,
                    "prior_status": "in_progress",
                    "verification": {"checks": ["pytest -q"]},
                },
            },
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"EV-{seq + 3:08d}",
                "event_seq": seq + 3,
                "ts": ts,
                "actor": "agent-impl",
                "action": "review",
                "payload": {"task_id": tid, "prior_status": "review", "decision": "approve"},
            },
        ]
        seq += 4
        for ev in events:
            lines.append(json.dumps(ev, ensure_ascii=False, separators=(",", ":")))
    activity_path = root / ".roadmap" / "activity.jsonl"
    with activity_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    ESAAService(root).project()


@pytest.mark.parametrize("cutoff_tasks", [1, 5, 10])
def test_snapshot_replay_matches_full_replay_at_cutoffs(tmp_path: Path, cutoff_tasks: int) -> None:
    _make_synthetic_store(tmp_path, num_tasks=12)
    before_seq = 1 + cutoff_tasks * 4
    snap = create_snapshot(tmp_path, before=before_seq)
    assert snap["snapshot_format_version"] == "2"

    svc = ESAAService(tmp_path)
    svc.project()
    snap_verify = svc.verify()
    full_verify = svc.verify_full()
    assert snap_verify == full_verify
    assert snap_verify["verify_status"] == "ok"

    snap_replay = load_verified_replay(tmp_path, full=False)
    full_replay = load_verified_replay(tmp_path, full=True)
    assert snap_replay.used_snapshot is True
    assert full_replay.used_snapshot is False

    r1, i1, l1 = materialize(parse_event_store(tmp_path))
    assert r1["meta"]["run"]["projection_hash_sha256"] == snap_verify["projection_hash_sha256"]
    assert len(i1["issues"]) >= 0
    assert len(l1["lessons"]) >= 0


def test_tampered_snapshot_falls_back_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_synthetic_store(tmp_path, num_tasks=4)
    snap = create_snapshot(tmp_path, before=9)
    snap_path = tmp_path / snap["snapshot_path"]
    raw = snap_path.read_text(encoding="utf-8")
    snap_path.write_text(raw.replace("Task SYN-000001", "Task XYN-000001"), encoding="utf-8")

    ESAAService(tmp_path).project()
    res = ESAAService(tmp_path).verify()
    captured = capsys.readouterr()
    assert "warning: ignoring snapshot" in captured.err
    assert "snapshot_hash_sha256 mismatch" in captured.err
    assert res["verify_status"] == "ok"


def test_unanchored_snapshot_falls_back_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_synthetic_store(tmp_path, num_tasks=4)
    snap = create_snapshot(tmp_path, before=9)
    activity_path = tmp_path / ".roadmap" / "activity.jsonl"
    lines = [ln for ln in activity_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Remove the snapshot.anchor event
    lines = [ln for ln in lines if '"snapshot.anchor"' not in ln]
    activity_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    ESAAService(tmp_path).project()
    res = ESAAService(tmp_path).verify()
    captured = capsys.readouterr()
    assert "warning: ignoring snapshot" in captured.err
    assert "snapshot.anchor" in captured.err
    assert res["verify_status"] == "ok"
    assert Path(tmp_path / snap["snapshot_path"]).exists()


def test_rewritten_prefix_or_wrong_projector_version_falls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_synthetic_store(tmp_path, num_tasks=4)
    snap = create_snapshot(tmp_path, before=9)
    snap_path = tmp_path / snap["snapshot_path"]
    doc = json.loads(snap_path.read_text(encoding="utf-8"))
    doc["snapshot"]["projector_version"] = "999"
    snap_path.write_text(json.dumps(doc), encoding="utf-8")

    res = ESAAService(tmp_path).verify()
    captured = capsys.readouterr()
    assert "projector_version mismatch" in captured.err
    assert res["verify_status"] == "ok"

    # Now restore valid snapshot but tamper offset in activity.jsonl
    snap2 = create_snapshot(tmp_path, before=13)
    activity_path = tmp_path / ".roadmap" / "activity.jsonl"
    raw_lines = activity_path.read_text(encoding="utf-8").splitlines()
    ev = json.loads(raw_lines[12])
    ev["ts"] = "2026-11-12T23:59:59.123Z"
    raw_lines[12] = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
    activity_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    ESAAService(tmp_path).project()
    capsys.readouterr()

    res2 = ESAAService(tmp_path).verify()
    captured2 = capsys.readouterr()
    assert "warning: ignoring snapshot" in captured2.err
    assert res2["verify_status"] == "ok"
    assert Path(tmp_path / snap2["snapshot_path"]).exists()


def test_verify_full_cli_ignores_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_synthetic_store(tmp_path, num_tasks=4)
    create_snapshot(tmp_path, before=9)
    ESAAService(tmp_path).project()
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "verify", "--full"]) == 0
    out_full = json.loads(capsys.readouterr().out)
    assert main(["--root", str(tmp_path), "verify"]) == 0
    out_snap = json.loads(capsys.readouterr().out)
    assert out_full == out_snap


def test_compaction_works_without_verify_ok_and_rejects_above_last_seq(tmp_path: Path) -> None:
    _make_synthetic_store(tmp_path, num_tasks=3)
    res = compact_event_store(tmp_path, before=9, dry_run=False)
    assert res["status"] == "compacted"
    with pytest.raises(ESAAError) as exc:
        compact_event_store(tmp_path, before=999999, dry_run=True)
    assert exc.value.code == "SNAPSHOT_BEFORE_UNVERIFIED"


@pytest.mark.slow
@pytest.mark.filterwarnings("ignore::pytest.PytestUnknownMarkWarning")
def test_snapshot_replay_200k_events_performance(tmp_path: Path) -> None:
    _make_synthetic_store(tmp_path, num_tasks=50000)
    create_snapshot(tmp_path, before=190000)
    svc = ESAAService(tmp_path)
    svc.project()

    t0 = time.monotonic()
    res = svc.verify()
    elapsed = time.monotonic() - t0
    print(f"200k_verify_elapsed={elapsed:.3f}s")
    assert res["verify_status"] == "ok"
    assert elapsed < 10.0
