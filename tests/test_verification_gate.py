import json

import pytest
from test_verification_config import CONFIG
from test_verification_executor import ready

from esaa.errors import ESAAError
from esaa.store import parse_event_store


def attest(svc, candidate, monkeypatch, success=True):
    import esaa.verification_executor as executor

    def execute(c, f):
        return {
            "id": c["id"],
            "image": c["image"],
            "status": "passed" if success else "failed",
            "stdout": "observed",
            "stderr": "",
            "exit_code": 0 if success else 1,
        }

    monkeypatch.setattr(executor, "execute_check", execute)
    result = svc.verification_run("T-C", candidate, "agent-impl")
    candidate["activity_event"]["verification"]["execution_id"] = result["run_id"]
    return result


def test_missing_failed_success_and_no_reexecution(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    with pytest.raises(ESAAError, match="execution_id"):
        svc.submit(candidate, actor="agent-impl")
    attest(svc, candidate, monkeypatch, False)
    with pytest.raises(ESAAError, match="did not pass"):
        svc.submit(candidate, actor="agent-impl")
    attest(svc, candidate, monkeypatch)
    import esaa.verification_executor as executor

    monkeypatch.setattr(executor, "execute_check", lambda *args: pytest.fail("complete reran checks"))
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
    svc.submit(candidate, actor="agent-impl", dry_run=True)
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    svc.submit(candidate, actor="agent-impl")
    assert (contract_bundle / "tetris.py").read_text() == "fixed\n"
    assert svc.task_state("T-C")["task"]["status"] == "review"
    assert svc.verify()["verify_status"] == "ok"
    svc.replay(write_views=False)


@pytest.mark.parametrize("change", ["candidate", "inputs", "config", "cycle", "other-task", "artifact"])
def test_stale_and_tampered(contract_bundle, monkeypatch, change):
    svc, candidate = ready(contract_bundle)
    result = attest(svc, candidate, monkeypatch)
    if change == "candidate":
        candidate["file_updates"][0]["content"] = "different\n"
    elif change == "inputs":
        (contract_bundle / "tetris.py").write_text("concurrent\n")
    elif change == "config":
        svc.verification_enable(CONFIG)
    elif change == "cycle":
        svc.submit(candidate, actor="agent-impl")
        svc.review_task("T-C", actor="agent-qa", decision="request_changes")
    elif change == "other-task":
        svc.create_task(
            "T-OTHER",
            task_kind="impl",
            title="other",
            boundary_grant=["tetris.py"],
            executable_checks=["unit"],
        )
        svc.claim_task("T-OTHER", actor="agent-impl")
        candidate["activity_event"]["task_id"] = "T-OTHER"
    else:
        (contract_bundle / result["results"][0]["logs"]["stdout"]["path"]).write_text("tampered")
    with pytest.raises(ESAAError):
        svc.submit(candidate, actor="agent-impl")


def test_final_lock_revalidates_and_does_not_apply(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    original = svc._append_events_transactionally
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()

    def concurrent(base, pending, **kwargs):
        (contract_bundle / "tetris.py").write_text("concurrent\n")
        return original(base, pending, **kwargs)

    monkeypatch.setattr(svc, "_append_events_transactionally", concurrent)
    with pytest.raises(ESAAError, match="verification belongs"):
        svc.submit(candidate, actor="agent-impl")
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    assert (contract_bundle / "tetris.py").read_text() == "concurrent\n"
    assert svc.task_state("T-C")["task"]["status"] == "in_progress"


def test_effect_commit_uses_lock(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    import esaa.submission as submission

    original = submission.commit_staged
    observed = []

    def commit(root, staged):
        assert (root / ".roadmap/activity.jsonl.lock").exists()
        observed.append(True)
        return original(root, staged)

    monkeypatch.setattr(submission, "commit_staged", commit)
    svc.submit(candidate, actor="agent-impl")
    assert observed


def test_adapter_path_obeys_evidence_gate(contract_bundle, monkeypatch):
    from esaa.adapters.mock import MockAgentAdapter

    svc, candidate = ready(contract_bundle)
    svc.adapter = MockAgentAdapter("agent-impl")
    monkeypatch.setattr(svc.adapter, "execute", lambda context: candidate)
    result = svc.run(steps=1)
    assert result["rejected"] == 1
    assert (contract_bundle / "tetris.py").read_text() == "old\n"
    attest(svc, candidate, monkeypatch)
    # A rejected invocation can impose cooldown; direct submit must still validate the same candidate.
    svc.submit(candidate, actor="agent-impl")
    assert svc.task_state("T-C")["task"]["status"] == "review"


def test_same_batch_cannot_change_other_verification_inputs(contract_bundle, monkeypatch):
    from esaa.events import make_event
    from esaa.file_effects import discard_staged, stage_and_compute
    from esaa.verification_gate import validate_pending

    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    events = parse_event_store(contract_bundle)
    seq = events[-1]["event_seq"] + 1
    staged, effects = stage_and_compute(contract_bundle, candidate["file_updates"])
    try:
        pending = [
            make_event(seq, "agent-impl", "complete", candidate["activity_event"]),
            make_event(
                seq + 1,
                "orchestrator",
                "orchestrator.file.write",
                {"task_id": "T-C", "files": ["tetris.py"], "effects": effects},
            ),
            make_event(
                seq + 2,
                "orchestrator",
                "orchestrator.file.write",
                {"task_id": "T-OTHER", "files": ["tetris.py"], "effects": []},
            ),
        ]
        with pytest.raises(ESAAError, match="batch modifies"):
            validate_pending(contract_bundle, events, pending)
    finally:
        discard_staged(staged)


def test_forged_result_payload_is_rejected(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    path = contract_bundle / ".roadmap/activity.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    event = next(e for e in events if e["action"] == "verification.run")
    event["payload"]["binding"]["candidate_sha256"] = "0" * 64
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ESAAError, match="integrity"):
        svc.submit(candidate, actor="agent-impl")


def test_adapter_can_deliver_preverified_candidate(contract_bundle, monkeypatch):
    from esaa.adapters.mock import MockAgentAdapter

    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    svc.adapter = MockAgentAdapter("agent-impl")
    monkeypatch.setattr(svc.adapter, "execute", lambda context: candidate)
    result = svc.run(steps=1)
    assert result["rejected"] == 0
    assert (contract_bundle / "tetris.py").read_text() == "fixed\n"
    assert svc.task_state("T-C")["task"]["status"] == "review"
