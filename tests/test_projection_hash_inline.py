from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from esaa.constants import PROJECTOR_VERSION, SCHEMA_VERSION
from esaa.errors import CorruptedStoreError
from esaa.events import make_event
from esaa.projector import materialize
from esaa.reject_codes import PROJECTION_DRIFT
from esaa.service import ESAAService
from esaa.snapshot import create_snapshot
from esaa.store import append_events, parse_event_store


def _run_cli(root: Path, *args: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "esaa", "--root", str(root), *args],
        env=env,
        text=True,
        capture_output=True,
    )
    data = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"raw": proc.stdout}
    return proc.returncode, data


def test_claim_task_create_and_complete_batch_inline_hashes(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)
    init_events = parse_event_store(contract_bundle)
    assert not any(ev["action"] in {"verify.start", "verify.ok"} for ev in init_events)
    assert "projection_hash_after" in init_events[-1]
    assert init_events[-1]["projector_version"] == PROJECTOR_VERSION

    # task.create appends 1 event
    before_create = len(parse_event_store(contract_bundle))
    svc.create_task("T-INLINE-1", "impl", "Inline hash task", outputs=["src/inline.txt"])
    after_create = parse_event_store(contract_bundle)
    assert len(after_create) == before_create + 1
    assert after_create[-1]["action"] == "task.create"
    assert after_create[-1]["schema_version"] == SCHEMA_VERSION
    assert "projection_hash_after" in after_create[-1]

    # claim appends 1 event
    before_claim = len(after_create)
    svc.claim_task("T-INLINE-1", actor="agent-impl")
    after_claim = parse_event_store(contract_bundle)
    assert len(after_claim) == before_claim + 1
    assert after_claim[-1]["action"] == "claim"
    assert "projection_hash_after" in after_claim[-1]

    # complete with file_updates appends complete + orchestrator.file.write; only last has hash
    before_complete = len(after_claim)
    svc.complete_task(
        "T-INLINE-1",
        actor="agent-impl",
        checks=["inline test"],
        file_updates=[{"path": "src/inline.txt", "content": "ok\n"}],
    )
    after_complete = parse_event_store(contract_bundle)
    batch = after_complete[before_complete:]
    assert [ev["action"] for ev in batch] == ["complete", "orchestrator.file.write"]
    assert "projection_hash_after" not in batch[0]
    assert "projection_hash_after" in batch[1]
    assert batch[1]["projector_version"] == PROJECTOR_VERSION
    assert svc.verify()["verify_status"] == "ok"


def test_projection_drift_detected_and_verify_exits_2(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.claim_task("T-1000", actor="agent-spec")

    activity_path = contract_bundle / ".roadmap" / "activity.jsonl"
    lines = activity_path.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    last["projection_hash_after"] = "0" * 64
    lines[-1] = json.dumps(last, ensure_ascii=False, separators=(",", ":"))
    activity_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(CorruptedStoreError) as exc_info:
        materialize(parse_event_store(contract_bundle))
    assert exc_info.value.code == PROJECTION_DRIFT

    rc, out = _run_cli(contract_bundle, "verify")
    assert rc == 2
    assert out["verify_status"] == "corrupted"
    assert out["error_code"] == PROJECTION_DRIFT


def test_previous_projector_version_hash_is_unchecked_without_failure(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.claim_task("T-1000", actor="agent-spec")

    activity_path = contract_bundle / ".roadmap" / "activity.jsonl"
    lines = activity_path.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    last["projector_version"] = "0"
    last["projection_hash_after"] = "0" * 64
    lines[-1] = json.dumps(last, ensure_ascii=False, separators=(",", ":"))
    activity_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = svc.verify()
    assert res["verify_status"] == "ok"
    assert res["hash_unchecked"] >= 1


def test_mixed_legacy_verify_ok_and_inline_hash_log(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)

    # Append a legacy 0.4.1 verify.start / verify.ok pair directly
    events = parse_event_store(contract_bundle)
    seq = len(events) + 1
    vs = make_event(seq, "orchestrator", "verify.start", {"strict": True})
    vs["schema_version"] = "0.4.1"
    vo = make_event(seq + 1, "orchestrator", "verify.ok", {"projection_hash_sha256": "a" * 64})
    vo["schema_version"] = "0.4.1"
    append_events(contract_bundle, [vs, vo])

    # Now perform a new 0.4.2 task.create + claim
    svc.create_task("T-MIX-1", "impl", "Mixed task", outputs=["src/mix.txt"])
    svc.claim_task("T-MIX-1", actor="agent-impl")
    ver = svc.verify()
    assert ver["verify_status"] == "ok"
    assert ver["hash_checked"] >= 2


def test_50k_events_inline_format_claim_and_verify_under_3s(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)
    base_events = parse_event_store(contract_bundle)
    seq = len(base_events) + 1

    # Build 50,000 events synthetically using the new inline format
    synthetic: list[dict] = []
    for idx in range(50):
        ev = make_event(
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
        synthetic.append(ev)
        seq += 1

    # Add 49,950 runner.metrics events + 1 final event with projection_hash_after
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

    append_events(contract_bundle, synthetic)
    from esaa.store import save_issues, save_lessons, save_roadmap

    save_roadmap(contract_bundle, roadmap)
    save_issues(contract_bundle, issues)
    save_lessons(contract_bundle, lessons)
    create_snapshot(contract_bundle, before=49000)

    t0 = time.perf_counter()
    ver = svc.verify()
    verify_elapsed = time.perf_counter() - t0
    assert ver["verify_status"] == "ok"
    assert verify_elapsed < 3.0, f"verify took {verify_elapsed:.2f}s"

    t1 = time.perf_counter()
    claimed = svc.claim_task("T-PERF-000", actor="agent-impl")
    claim_elapsed = time.perf_counter() - t1
    assert claimed["status"] == "accepted"
    assert claim_elapsed < 3.0, f"claim took {claim_elapsed:.2f}s"
