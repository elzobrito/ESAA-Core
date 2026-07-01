from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _workspace(tmp_path: Path, repo_root: Path) -> Path:
    root = tmp_path / "workspace"
    roadmap = root / ".roadmap"
    roadmap.mkdir(parents=True)
    for name in (
        "AGENT_CONTRACT.yaml",
        "RUNTIME_POLICY.yaml",
        "agent_result.schema.json",
        "roadmap.schema.json",
    ):
        shutil.copy2(repo_root / ".roadmap" / name, roadmap / name)
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "roadmap.schema.json",
        roadmap / "roadmap.schema.json",
    )
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "agent_result.schema.json",
        roadmap / "agent_result.schema.json",
    )
    ESAAService(root).init(force=True)
    return root


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _put_task_in_review(root: Path, task_id: str, *, required_review_mode: str | None = None) -> None:
    service = ESAAService(root)
    service.create_task(
        task_id,
        task_kind="spec",
        title=f"{task_id} title",
        outputs=[f"docs/spec/{task_id}.md"],
        required_review_mode=required_review_mode,
    )
    service.claim_task(task_id, actor="agent-spec")
    service.complete_task(
        task_id,
        actor="agent-spec",
        checks=["spec complete"],
        file_updates=[{"path": f"docs/spec/{task_id}.md", "content": "# Spec\n"}],
    )


def _last_review_payload(root: Path, task_id: str) -> dict:
    reviews = [
        event["payload"]
        for event in parse_event_store(root)
        if event["action"] == "review" and event["payload"]["task_id"] == task_id
    ]
    assert reviews
    return reviews[-1]


def test_required_review_mode_missing_or_mismatched_fails_before_append(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    _put_task_in_review(root, "T-REQ", required_review_mode="governance")
    service = ESAAService(root)

    before = len(parse_event_store(root))
    with pytest.raises(ESAAError) as missing:
        service.review_task("T-REQ", actor="agent-qa", decision="approve")
    assert missing.value.code == "REVIEW_MODE_REQUIRED"
    assert len(parse_event_store(root)) == before

    with pytest.raises(ESAAError) as mismatch:
        service.review_task("T-REQ", actor="agent-qa", decision="request_changes", review_mode="security")
    assert mismatch.value.code == "REVIEW_MODE_MISMATCH"
    assert len(parse_event_store(root)) == before


def test_request_changes_and_approve_require_matching_review_mode(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    _put_task_in_review(root, "T-REQ", required_review_mode="governance")
    service = ESAAService(root)

    request_changes = service.review_task(
        "T-REQ", actor="agent-qa", decision="request_changes", review_mode="governance"
    )
    assert request_changes["task"]["status"] == "in_progress"
    assert _last_review_payload(root, "T-REQ")["review_mode"] == "governance"

    service.complete_task("T-REQ", actor="agent-spec", checks=["changes addressed"])
    approve = service.review_task("T-REQ", actor="agent-qa", decision="approve", review_mode="governance")
    assert approve["task"]["status"] == "done"
    assert _last_review_payload(root, "T-REQ")["review_mode"] == "governance"


def test_optional_review_mode_is_preserved_when_task_does_not_require_it(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    _put_task_in_review(root, "T-OPTIONAL")

    result = _run_cli(
        root,
        "review",
        "T-OPTIONAL",
        "--actor",
        "agent-qa",
        "--decision",
        "approve",
        "--review-mode",
        "security",
    )

    assert result["task"]["status"] == "done"
    assert _last_review_payload(root, "T-OPTIONAL")["review_mode"] == "security"


def test_invalid_review_mode_from_agent_result_fails_before_append(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    _put_task_in_review(root, "T-INVALID")
    service = ESAAService(root)

    before = len(parse_event_store(root))
    with pytest.raises(ESAAError) as exc:
        service.submit(
            {
                "activity_event": {
                    "action": "review",
                    "task_id": "T-INVALID",
                    "prior_status": "review",
                    "decision": "approve",
                    "review_mode": "audit",
                    "tasks": ["T-INVALID"],
                }
            },
            actor="agent-qa",
        )

    assert exc.value.code == "SCHEMA_INVALID"
    assert len(parse_event_store(root)) == before
