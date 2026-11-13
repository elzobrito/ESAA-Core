"""Regression tests for 50k-event claim performance under 3s (HF-ISS-AUD-O2-CLAIM-PERFORMANCE-20261113)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from esaa.constants import PROJECTOR_VERSION
from esaa.events import make_event
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.snapshot import create_snapshot
from esaa.store import append_events, parse_event_store, save_issues, save_lessons, save_roadmap


def _seed_50k_store(root: Path, *, with_snapshot: bool = True) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=False)
    base_events = parse_event_store(root)
    seq = len(base_events) + 1

    synthetic: list[dict] = []
    for idx in range(50):
        synthetic.append(
            make_event(
                seq,
                "orchestrator",
                "task.create",
                {
                    "task_id": f"T-PERF-{idx:03d}",
                    "task_kind": "impl",
                    "title": f"Perf task {idx}",
                    "outputs": {"files": []},
                },
            )
        )
        seq += 1

    while len(base_events) + len(synthetic) < 49999:
        synthetic.append(
            make_event(
                seq,
                "orchestrator",
                "runner.metrics",
                {"task_id": "T-PERF-000", "duration_ms": 1},
            )
        )
        seq += 1

    last_ev = make_event(seq, "orchestrator", "runner.metrics", {"task_id": "T-PERF-000", "duration_ms": 1})
    roadmap, issues, lessons = materialize(base_events + synthetic + [last_ev])
    last_ev["projection_hash_after"] = roadmap["meta"]["run"]["projection_hash_sha256"]
    last_ev["projector_version"] = PROJECTOR_VERSION
    synthetic.append(last_ev)

    append_events(root, synthetic)
    save_roadmap(root, roadmap)
    save_issues(root, issues)
    save_lessons(root, lessons)
    if with_snapshot:
        create_snapshot(root, before=49000)
    return svc


def test_cold_cli_claim_50k_events_under_3s(contract_bundle: Path) -> None:
    _seed_50k_store(contract_bundle, with_snapshot=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "esaa",
            "--root",
            str(contract_bundle),
            "--runner",
            "codex",
            "claim",
            "T-PERF-000",
            "--actor",
            "agent-impl",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "accepted"
    assert elapsed < 3.0, f"cold CLI claim took {elapsed:.3f}s (>= 3.0s)"
