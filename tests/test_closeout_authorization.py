"""Supplied credentials cannot silently become unsigned legacy operations."""

import json

import pytest
from test_actor_registration import _copy_runtime, _ready_task

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.service import ESAAService


@pytest.mark.parametrize("action", ["claim", "complete", "review"])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("authorization", [{}, {"invalid": "envelope"}])
def test_supplied_authorization_inactive_is_rejected(tmp_path, repo_root, action, dry_run, authorization):
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    if action == "complete":
        svc.claim_task("T-1000", actor="agent-spec")
    elif action == "review":
        _ready_task(svc)
    event = {
        "action": action,
        "task_id": "T-1000",
        "prior_status": {"claim": "todo", "complete": "in_progress", "review": "review"}[action],
    }
    if action == "complete":
        event["verification"] = {"checks": ["observed"]}
    if action == "review":
        event["decision"] = "approve"
        event["tasks"] = ["T-1000"]
    actor = "agent-qa" if action == "review" else "agent-spec"
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    with pytest.raises(ESAAError) as exc:
        svc.submit({"activity_event": event}, actor=actor, authorization=authorization, dry_run=dry_run)
    assert exc.value.code == "ACTOR_BOOTSTRAP_REQUIRED"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before


def test_cli_supplied_authorization_rejected_and_none_legacy_preserved(tmp_path, repo_root, capsys):
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _ready_task(svc)
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"invalid": "envelope"}))
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "review",
                "T-1000",
                "--actor",
                "agent-qa",
                "--decision",
                "approve",
                "--authorization",
                str(auth),
                "--dry-run",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["error_code"] == "ACTOR_BOOTSTRAP_REQUIRED"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    assert svc.review_task("T-1000", actor="agent-qa", decision="approve")["status"] == "accepted"
