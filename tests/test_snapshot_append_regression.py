"""Regression tests for safe append after snapshot (HF-ISS-AUD-O2-120-SNAPSHOT-HASH-20261112)."""

from __future__ import annotations

from pathlib import Path

import pytest

from esaa.bootstrap import bootstrap_workspace
from esaa.service import ESAAService
from esaa.snapshot import create_snapshot
from esaa.store_runtime import init_hash_chain


def _seed_store_with_metrics(root: Path, count: int = 195) -> ESAAService:
    bootstrap_workspace(root)
    svc = ESAAService(root)
    svc.init()
    svc.create_task(
        task_id="T-BENCH",
        task_kind="impl",
        title="Benchmark task",
        description="Task used for snapshot append regression",
        outputs=["src/bench.py"],
    )
    for i in range(count):
        svc.record_runner_metrics(
            {
                "runner_id": "codex",
                "runner_kind": "cli",
                "actor": "agent-impl",
                "task_id": "T-BENCH",
                "command_surface": "cli",
                "status": "success",
                "duration_ms": i,
            }
        )
    svc.project()
    return svc


def test_create_claim_complete_review_after_snapshot_195_metrics(tmp_path: Path) -> None:
    svc = _seed_store_with_metrics(tmp_path, count=195)
    create_snapshot(tmp_path, before=100)

    created = svc.create_task(
        task_id="T-NEW",
        task_kind="impl",
        title="New task after snapshot",
        description="Created after snapshot(before=100)",
        outputs=["src/new_mod.py"],
    )
    assert created["verify_status"] == "ok"

    svc.claim_task("T-BENCH", actor="agent-impl")
    svc.complete_task("T-BENCH", actor="agent-impl", checks=["pytest -q"])
    svc.review_task("T-BENCH", actor="agent-qa", decision="approve")

    svc.claim_task("T-NEW", actor="agent-impl")
    svc.complete_task("T-NEW", actor="agent-impl", checks=["pytest -q"])
    svc.review_task("T-NEW", actor="agent-qa", decision="approve")

    v_snap = svc.verify()
    v_full = svc.verify_full()
    assert v_snap["verify_status"] == "ok"
    assert v_snap == v_full


@pytest.mark.parametrize("cutoff", [0, 1, 50, 198])
def test_append_after_snapshot_arbitrary_cutoffs(tmp_path: Path, cutoff: int) -> None:
    svc = _seed_store_with_metrics(tmp_path, count=195)
    create_snapshot(tmp_path, before=cutoff)

    svc.create_task(
        task_id="T-CUT",
        task_kind="impl",
        title="Cutoff task",
        description="Task created at arbitrary snapshot cutoff",
        outputs=["src/cut.py"],
    )
    svc.claim_task("T-CUT", actor="agent-impl")
    svc.complete_task("T-CUT", actor="agent-impl", checks=["pytest -q"])
    svc.review_task("T-CUT", actor="agent-qa", decision="approve")

    v_snap = svc.verify()
    v_full = svc.verify_full()
    assert v_snap["verify_status"] == "ok"
    assert v_snap == v_full


def test_append_after_snapshot_with_hash_chain(tmp_path: Path) -> None:
    svc = _seed_store_with_metrics(tmp_path, count=20)
    init_hash_chain(tmp_path)
    create_snapshot(tmp_path, before=10)

    svc.create_task(
        task_id="T-CHAIN",
        task_kind="impl",
        title="Chained task",
        description="Task created after snapshot with active hash chain",
        outputs=["src/chain.py"],
    )
    svc.claim_task("T-CHAIN", actor="agent-impl")
    svc.complete_task("T-CHAIN", actor="agent-impl", checks=["pytest -q"])
    svc.review_task("T-CHAIN", actor="agent-qa", decision="approve")

    v_snap = svc.verify()
    v_full = svc.verify_full()
    assert v_snap["verify_status"] == "ok"
    assert v_snap["chain_status"] == "ok"
    assert v_snap == v_full


def test_append_falls_back_cleanly_when_snapshot_tampered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    svc = _seed_store_with_metrics(tmp_path, count=10)
    snap = create_snapshot(tmp_path, before=5)
    snap_path = tmp_path / snap["snapshot_path"]
    snap_path.write_text(
        snap_path.read_text(encoding="utf-8").replace("Benchmark task", "Tampered task"),
        encoding="utf-8",
    )

    svc.create_task(
        task_id="T-FALLBACK",
        task_kind="impl",
        title="Fallback task",
        description="Created when snapshot is tampered",
        outputs=["src/fb.py"],
    )
    captured = capsys.readouterr()
    assert "warning: ignoring snapshot" in captured.err
    assert svc.verify_full()["verify_status"] == "ok"
