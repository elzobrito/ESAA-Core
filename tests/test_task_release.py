import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from test_operator_commands import _seed, _workspace

from esaa import cli
from esaa.errors import ESAAError
from esaa.events import make_event
from esaa.projector import materialize
from esaa.runtime_policy import count_penalizing_rejections, is_in_cooldown
from esaa.store import parse_event_store


@contextmanager
def raises_code(code):
    with pytest.raises(ESAAError) as exc:
        yield
    assert exc.value.code == code


def setup_service(contract_bundle, repo_root, monkeypatch, strict=False):
    monkeypatch.setenv("ESAA_RUNNER_ID", "human-terminal")
    s = _workspace(contract_bundle, repo_root, strict=strict)
    _seed(s)
    return s


def test_release_reclaim_and_history(contract_bundle, repo_root, monkeypatch):
    s = setup_service(contract_bundle, repo_root, monkeypatch)
    s.claim_task("T-A", "agent-old")
    before = parse_event_store(contract_bundle)
    dry = s.release_task("T-A", reason="stopped", dry_run=True)
    assert dry["status"] == "dry_run"
    assert parse_event_store(contract_bundle) == before
    s.release_task("T-A", reason="stopped")
    after = parse_event_store(contract_bundle)
    assert after[: len(before)] == before
    task = s.task_state("T-A")["task"]
    assert task["status"] == "todo" and "assigned_to" not in task and "started_at" not in task
    s.claim_task("T-A", "agent-new")
    assert s.task_state("T-A")["task"]["assigned_to"] == "agent-new"
    assert s.verify()["verify_status"] == "ok"


def test_reset_max_attempts_and_cooldown(contract_bundle, repo_root, monkeypatch):
    s = setup_service(contract_bundle, repo_root, monkeypatch)
    for _ in range(3):
        s.reject_output("T-A", "SCHEMA_INVALID", "claim", "bad input")
    with raises_code("MAX_ATTEMPTS_EXCEEDED"):
        s.claim_task("T-A", "agent-new")
    assert not s.eligible()["eligible"]
    s.release_task("T-A", reason="input corrected")
    events = parse_event_store(contract_bundle)
    assert count_penalizing_rejections(events, "T-A") == 0
    assert not is_in_cooldown(events, "T-A", datetime.now(UTC), timedelta(minutes=2))
    assert s.eligible()["eligible"][0]["task_id"] == "T-A"
    s.claim_task("T-A", "agent-new")


def test_stale_listing_read_only(contract_bundle, repo_root, monkeypatch):
    s = setup_service(contract_bundle, repo_root, monkeypatch)
    s.claim_task("T-A", "agent-old")
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(hours=2)

    monkeypatch.setattr("esaa.execution.datetime", Future)
    result = s.eligible()
    assert result["stale_claims"][0]["task_id"] == "T-A"
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    s.complete_task("T-A", "agent-old", checks=["checked"])
    s.review_task("T-A", "agent-qa", "request_changes")
    assert s.eligible()["stale_claims"][0]["task_id"] == "T-A"
    s.release_task("T-A", reason="stalled")
    assert s.eligible()["stale_claims"] == []


def test_strict_and_cli(contract_bundle, repo_root, monkeypatch, capsys):
    s = setup_service(contract_bundle, repo_root, monkeypatch, strict=True)
    s.claim_task("T-A", "agent-impl")
    monkeypatch.setenv("ESAA_RUNNER_ID", "codex")
    before = parse_event_store(contract_bundle)
    with raises_code("OPERATOR_REQUIRED"):
        s.release_task("T-A", reason="stop")
    assert cli.main(["--root", str(contract_bundle), "task", "release", "T-A", "--reason", "stop"]) == 1
    assert json.loads(capsys.readouterr().err)["error_code"] == "OPERATOR_REQUIRED"
    assert parse_event_store(contract_bundle) == before
    monkeypatch.setenv("ESAA_RUNNER_ID", "human-terminal")
    assert cli.main(["--root", str(contract_bundle), "task", "release", "T-A", "--reason", "stop"]) == 0
    assert s.task_state("T-A")["task"]["status"] == "todo"


def test_invalid_release_and_stale_snapshot(contract_bundle, repo_root, monkeypatch):
    s = setup_service(contract_bundle, repo_root, monkeypatch)
    for reason in ("", "  "):
        with raises_code("INVALID_ARGUMENT"):
            s.release_task("T-A", reason=reason)
    with raises_code("TASK_NOT_FOUND"):
        s.release_task("missing", reason="stop")
    events = parse_event_store(contract_bundle)
    stale = make_event(
        len(events) + 1,
        "orchestrator",
        "task.release",
        {
            "task_id": "T-A",
            "reason": "stop",
            "previous": {"status": "in_progress", "assigned_to": "other", "started_at": None},
        },
    )
    with raises_code("PRIOR_STATUS_MISMATCH"):
        materialize(events + [stale])
    s.claim_task("T-A", "agent-impl")
    s.complete_task("T-A", "agent-impl", checks=["verified"])
    with raises_code("INVALID_TRANSITION"):
        s.release_task("T-A", reason="stop")
    s.review_task("T-A", "agent-qa", "approve")
    with raises_code("IMMUTABLE_DONE_VIOLATION"):
        s.release_task("T-A", reason="stop")


def test_release_checks_latest_prefix_under_lock(contract_bundle, repo_root, monkeypatch):
    s = setup_service(contract_bundle, repo_root, monkeypatch)
    s.claim_task("T-A", "agent-old")
    original = s._commit_orchestrator_events

    def racing_commit(candidates, **kwargs):
        if candidates[0]["action"] == "task.release":
            s.reject_output("T-A", "SCHEMA_INVALID", "complete", "concurrent change")
        return original(candidates, **kwargs)

    monkeypatch.setattr(s, "_commit_orchestrator_events", racing_commit)
    with raises_code("PRIOR_STATUS_MISMATCH"):
        s.release_task("T-A", reason="stopped")
    assert s.task_state("T-A")["task"]["status"] == "in_progress"
    assert not any(e["action"] == "task.release" for e in parse_event_store(contract_bundle))
