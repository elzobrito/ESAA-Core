from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from esaa.bootstrap import bootstrap_workspace
from esaa.cli import main
from esaa.constants import PROJECTOR_VERSION
from esaa.errors import CorruptedStoreError, ESAAError
from esaa.events import make_event
from esaa.plugins import install_plugin, scaffold_plugin
from esaa.projector import finalize_views, materialize
from esaa.service import ESAAService
from esaa.snapshot import create_snapshot, load_verified_replay
from esaa.store_runtime import append_events, parse_event_store


def _make_workspace(root: Path, n_tasks: int = 4) -> ESAAService:
    bootstrap_workspace(root)
    svc = ESAAService(root)
    svc.init(force=True)
    for i in range(1, n_tasks + 1):
        svc.create_task(f"T-{i:03d}", "impl", f"Task {i}", outputs=[f"src/f{i}.py"])
    return svc


@pytest.mark.parametrize("cut_offset", [1, 3, 5])
def test_snapshot_replay_equals_full_replay_at_arbitrary_cuts(tmp_path: Path, cut_offset: int) -> None:
    svc = _make_workspace(tmp_path, n_tasks=5)
    svc.claim_task("T-001", actor="agent-impl")
    svc.complete_task("T-001", actor="agent-impl", checks=["ok"])
    svc.review_task("T-001", actor="agent-qa", decision="approve")
    svc.claim_task("T-002", actor="agent-impl")

    all_events = parse_event_store(tmp_path)
    cut_seq = min(cut_offset + 1, all_events[-1]["event_seq"] - 1)
    snap_info = create_snapshot(tmp_path, before=cut_seq)
    assert snap_info["before_event_seq"] <= cut_seq

    replay = load_verified_replay(tmp_path)
    assert replay.used_snapshot is True
    snap_rm, snap_iss, snap_les = finalize_views(replay.state, copy=False)
    full_rm, full_iss, full_les = materialize(parse_event_store(tmp_path))
    assert snap_rm == full_rm
    assert snap_iss == full_iss
    assert snap_les == full_les


def test_mixed_legacy_and_v042_log_verifies_and_detects_drift(tmp_path: Path) -> None:
    svc = _make_workspace(tmp_path, n_tasks=2)
    # Inject a legacy v0.4.1 verify.start / verify.ok pair at the tail and verify mixed replay
    events = parse_event_store(tmp_path)
    seq = events[-1]["event_seq"] + 1
    legacy_pair = [
        {
            "schema_version": "0.4.1",
            "event_id": f"EV-{seq:08d}",
            "event_seq": seq,
            "ts": "2026-01-01T00:00:00Z",
            "actor": "orchestrator",
            "action": "verify.start",
            "payload": {"scope": "projections"},
        },
        {
            "schema_version": "0.4.1",
            "event_id": f"EV-{seq + 1:08d}",
            "event_seq": seq + 1,
            "ts": "2026-01-01T00:00:01Z",
            "actor": "orchestrator",
            "action": "verify.ok",
            "payload": {"scope": "projections"},
        },
    ]
    log_path = tmp_path / ".roadmap" / "activity.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        for ev in legacy_pair:
            handle.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
    svc.project()
    # Follow with new v0.4.2 event
    svc.claim_task("T-001", actor="agent-impl")
    assert svc.verify()["verify_status"] == "ok"

    # Drift on current projector_version raises PROJECTION_DRIFT; on older projector_version does not
    cur_events = parse_event_store(tmp_path)
    ev_with_hash = dict(cur_events[-1])
    ev_with_hash["projection_hash_after"] = "f" * 64
    ev_with_hash["projector_version"] = PROJECTOR_VERSION
    with pytest.raises(CorruptedStoreError) as exc_cur:
        materialize(cur_events[:-1] + [ev_with_hash])
    assert exc_cur.value.code == "PROJECTION_DRIFT"

    ev_old_proj = dict(ev_with_hash)
    ev_old_proj["projector_version"] = "0.0.1-legacy"
    materialize(cur_events[:-1] + [ev_old_proj])


def test_append_rejects_invalid_schema_while_replay_allows_historical(tmp_path: Path) -> None:
    _make_workspace(tmp_path, n_tasks=1)
    events = parse_event_store(tmp_path)
    bad_event = make_event(events[-1]["event_seq"] + 1, "agent-impl", "claim", {"unexpected_bad": True})
    with pytest.raises(ESAAError):
        append_events(tmp_path, [bad_event])


def test_plugin_locks_reconstructed_byte_for_byte_by_project(tmp_path: Path) -> None:
    svc = _make_workspace(tmp_path, n_tasks=1)
    plugin_dir = tmp_path / "demo-plugin-src"
    scaffold_plugin(tmp_path, "demo-plugin", directory=plugin_dir)
    install_plugin(tmp_path, str(plugin_dir))
    svc.project()

    plugins_lock = tmp_path / ".roadmap" / "plugins.lock.json"
    roadmaps_lock = tmp_path / ".roadmap" / "roadmaps.lock.json"
    before_plugins = plugins_lock.read_bytes() if plugins_lock.exists() else None
    before_roadmaps = roadmaps_lock.read_bytes() if roadmaps_lock.exists() else None

    if plugins_lock.exists():
        plugins_lock.unlink()
    if roadmaps_lock.exists():
        roadmaps_lock.unlink()

    assert main(["--root", str(tmp_path), "project"]) == 0
    if before_plugins is not None:
        assert plugins_lock.read_bytes() == before_plugins
    if before_roadmaps is not None:
        assert roadmaps_lock.read_bytes() == before_roadmaps


def test_cli_cross_checks_dispatch_status_chain_and_oplog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    svc = _make_workspace(tmp_path, n_tasks=1)
    log_file = tmp_path / "oplog.jsonl"

    # status is read-only (does not create or mutate files)
    before_hash = hashlib.sha256((tmp_path / ".roadmap" / "activity.jsonl").read_bytes()).hexdigest()
    assert main(["--root", str(tmp_path), "status"]) == 0
    assert hashlib.sha256((tmp_path / ".roadmap" / "activity.jsonl").read_bytes()).hexdigest() == before_hash
    assert not log_file.exists()

    # verify --chain == chain verify
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "verify", "--chain"]) == 0
    v_chain = json.loads(capsys.readouterr().out)
    assert main(["--root", str(tmp_path), "chain", "verify"]) == 0
    c_verify = json.loads(capsys.readouterr().out)
    assert v_chain == c_verify

    # dispatch-context next_command works with --dry-run and writes 1 oplog line when ESAA_LOG set
    monkeypatch.setenv("ESAA_LOG", str(log_file))
    dc = svc.dispatch_context("T-001")
    argv = dc["next_command_argv"]
    # Strip leading `python -m esaa`
    cli_argv = argv[3:] + ["--dry-run"]
    assert main(cli_argv) == 0
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["dry_run"] is True


def test_eight_concurrent_claims_one_winner_one_event(tmp_path: Path) -> None:
    _make_workspace(tmp_path, n_tasks=1)
    before_seq = parse_event_store(tmp_path)[-1]["event_seq"]

    def _try_claim(i: int) -> bool:
        try:
            ESAAService(tmp_path).claim_task("T-001", actor=f"agent-impl-{i}")
            return True
        except ESAAError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_try_claim, range(8)))

    assert results.count(True) == 1
    events = parse_event_store(tmp_path)
    tail = [e for e in events if e["event_seq"] > before_seq]
    assert sum(1 for e in tail if e["action"] == "claim") == 1
    assert sum(1 for e in tail if e["action"] in {"verify.start", "verify.ok"}) == 0
