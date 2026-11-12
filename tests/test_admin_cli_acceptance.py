"""Tests for AUD-O1-050 (GOV-10 and GOV-11).

(1) 16 parallel task create calls on distinct tasks succeed and verify passes.
(2) Three complete submissions with BOUNDARY_VIOLATION record output.rejected,
    and the fourth attempt is blocked with MAX_ATTEMPTS_EXCEEDED.
(3) PRIOR_STATUS_MISMATCH, DEPENDENCY_NOT_DONE, and TASK_SUPERSEDED do not count
    towards the task attempt limit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from esaa.service import ESAAService
from esaa.store import parse_event_store


def _run_cli(root: Path, *args: str) -> tuple[int, dict[str, Any], str]:
    """Execute CLI in a real subprocess with PYTHONPATH set."""
    env = dict(os.environ)
    env["PYTHONPATH"] = "src:."
    cmd = [sys.executable, "-B", "-m", "esaa", "--root", str(root), *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    out_json = {}
    if res.stdout.strip():
        try:
            out_json = json.loads(res.stdout)
        except json.JSONDecodeError:
            pass
    err_json = {}
    if res.stderr.strip():
        try:
            err_json = json.loads(res.stderr)
        except json.JSONDecodeError:
            pass
    return res.returncode, out_json or err_json, res.stderr


def _create_task_worker(args: tuple[str, str, str]) -> tuple[int, dict[str, Any], str]:
    root_str, task_id, title = args
    return _run_cli(Path(root_str), "task", "create", task_id, "--kind", "impl", "--title", title)


def test_16_parallel_task_create_distinct_tasks(contract_bundle: Path) -> None:
    """GOV-10: 16 parallel task creates of distinct tasks succeed without EVENT_SEQ_NON_MONOTONIC."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True)

    task_count = 16
    tasks = [(str(contract_bundle), f"T-{i:03d}", f"Concurrent task {i}") for i in range(task_count)]

    with ProcessPoolExecutor(max_workers=task_count) as executor:
        results = list(executor.map(_create_task_worker, tasks))

    for rc, out, err in results:
        if rc != 0:
            pytest.fail(f"Task create failed: out={out} err={err}", pytrace=False)
        assert out.get("status") == "accepted", f"Unexpected status: {out}"

    # Verify log and projections
    v = svc.verify()
    assert v["verify_status"] == "ok", f"Verify failed: {v}"

    events = parse_event_store(contract_bundle)
    created_tasks = [e for e in events if e.get("action") == "task.create"]
    assert len(created_tasks) == task_count

    # Check that event_seq in event store is strictly monotonic: 1..len(events)
    seqs = [e["event_seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1))


def test_three_complete_boundary_violations_record_rejected_and_fourth_fails(contract_bundle: Path) -> None:
    """GOV-11: 3 complete submissions with BOUNDARY_VIOLATION record output.rejected; 4th yields MAX_ATTEMPTS_EXCEEDED."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True)
    svc.create_task("T-BV", "impl", "Boundary task", outputs=["src/valid.txt"])
    svc.claim_task("T-BV", actor="agent-impl")

    bad_file = contract_bundle / "bad_updates.json"
    bad_file.write_text(json.dumps([{"path": ".roadmap/forbidden.txt", "content": "evil"}]), encoding="utf-8")

    # Three complete submissions that fail with BOUNDARY_VIOLATION
    for attempt in range(1, 4):
        rc, payload, _err = _run_cli(
            contract_bundle,
            "complete",
            "T-BV",
            "--actor",
            "agent-impl",
            "--check",
            "unit-test",
            "--file-updates",
            str(bad_file),
        )
        assert rc == 1
        assert payload.get("error_code") == "BOUNDARY_VIOLATION"

        # Check that output.rejected was recorded
        events = parse_event_store(contract_bundle)
        rejections = [
            e
            for e in events
            if e.get("action") == "output.rejected" and (e.get("payload") or {}).get("task_id") == "T-BV"
        ]
        assert len(rejections) == attempt

    # Fourth attempt: blocked by MAX_ATTEMPTS_EXCEEDED
    rc, payload, _err = _run_cli(
        contract_bundle,
        "complete",
        "T-BV",
        "--actor",
        "agent-impl",
        "--check",
        "unit-test",
        "--file-updates",
        str(bad_file),
    )
    assert rc == 1
    assert payload.get("error_code") == "MAX_ATTEMPTS_EXCEEDED"

    # Total rejections stay at 3 (MAX_ATTEMPTS_EXCEEDED does not record an additional output.rejected)
    events = parse_event_store(contract_bundle)
    rejections = [
        e
        for e in events
        if e.get("action") == "output.rejected" and (e.get("payload") or {}).get("task_id") == "T-BV"
    ]
    assert len(rejections) == 3


def test_non_penalizing_errors_do_not_increment_attempts(contract_bundle: Path, repo_root: Path) -> None:
    """GOV-11: PRIOR_STATUS_MISMATCH, DEPENDENCY_NOT_DONE, and TASK_SUPERSEDED do not record output.rejected."""
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "roadmap.schema.json",
        contract_bundle / ".roadmap" / "roadmap.schema.json",
    )
    svc = ESAAService(contract_bundle)
    svc.init(force=True)

    # 1. DEPENDENCY_NOT_DONE
    svc.create_task("T-DEP-A", "impl", "Dependency A", outputs=["src/a.txt"])
    svc.create_task("T-DEP-B", "impl", "Dependency B", outputs=["src/b.txt"], depends_on=["T-DEP-A"])

    rc, payload, _err = _run_cli(contract_bundle, "claim", "T-DEP-B", "--actor", "agent-impl")
    assert rc == 1
    assert payload.get("error_code") == "DEPENDENCY_NOT_DONE"

    # 2. TASK_SUPERSEDED
    svc.create_task("T-OLD", "impl", "Old task", outputs=["src/old.txt"])
    svc.create_task("T-NEW", "impl", "New task", outputs=["src/new.txt"], supersedes=["T-OLD"])

    rc, payload, _err = _run_cli(contract_bundle, "claim", "T-OLD", "--actor", "agent-impl")
    assert rc == 1
    assert payload.get("error_code") == "TASK_SUPERSEDED"

    # 3. PRIOR_STATUS_MISMATCH
    submit_file = contract_bundle / "submit_mismatch.json"
    submit_file.write_text(
        json.dumps(
            {
                "activity_event": {
                    "action": "complete",
                    "task_id": "T-DEP-A",
                    "prior_status": "in_progress",  # Real is "todo"
                    "verification": {"checks": ["unit"]},
                }
            }
        ),
        encoding="utf-8",
    )
    rc, payload, _err = _run_cli(contract_bundle, "submit", str(submit_file), "--actor", "agent-impl")
    assert rc == 1
    assert payload.get("error_code") == "PRIOR_STATUS_MISMATCH"

    # Confirm that NO output.rejected events were appended for any of these
    events = parse_event_store(contract_bundle)
    rejection_events = [e for e in events if e.get("action") == "output.rejected"]
    assert len(rejection_events) == 0

    # Ensure tasks can still be claimed/completed normally (attempts were not consumed)
    svc.claim_task("T-DEP-A", actor="agent-impl")
    assert svc.task_state("T-DEP-A")["task"]["status"] == "in_progress"
