from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest
import yaml

from esaa.cli import main
from esaa.dispatch import build_minimal_context
from esaa.errors import ESAAError
from esaa.events import make_event
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store


@pytest.fixture
def repo_root() -> Path:
    return Path.cwd()


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
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "lessons.schema.json",
        roadmap / "lessons.schema.json",
    )
    ESAAService(root).init(force=True, with_demo_tasks=True)
    return root


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _task(root: Path, task_id: str) -> dict:
    return ESAAService(root).task_state(task_id)["task"]


def test_g07_task_review_projection_and_dispatch_flow(tmp_path: Path, repo_root: Path) -> None:
    root = _workspace(tmp_path, repo_root)
    service = ESAAService(root)

    _run_cli(
        root,
        "task",
        "create",
        "T-G07-E2E",
        "--kind",
        "spec",
        "--title",
        "G07 e2e spec",
        "--output",
        "docs/spec/g07-e2e.md",
        "--task-type",
        "governance",
        "--acceptance-criterion",
        "Projection derives superseded_by",
        "--acceptance-criterion",
        "Review mode is enforced before append",
        "--required-review-mode",
        "governance",
        "--supersedes",
        "T-1000",
    )

    created = _task(root, "T-G07-E2E")
    assert created["task_type"] == "governance"
    assert created["acceptance_criteria"] == [
        "Projection derives superseded_by",
        "Review mode is enforced before append",
    ]
    assert created["required_review_mode"] == "governance"
    assert created["supersedes"] == ["T-1000"]
    assert _task(root, "T-1000")["superseded_by"] == ["T-G07-E2E"]

    service.claim_task("T-G07-E2E", actor="agent-spec")
    context = service.dispatch_context("T-G07-E2E")
    assert context["task"]["task_type"] == "governance"
    assert context["task"]["required_review_mode"] == "governance"
    assert context["task"]["acceptance_criteria"][0] == "Projection derives superseded_by"
    assert context["task"].get("superseded_by", []) == []

    service.complete_task(
        "T-G07-E2E",
        actor="agent-spec",
        checks=["Spec acceptance criteria covered"],
        file_updates=[{"path": "docs/spec/g07-e2e.md", "content": "# G07 E2E\n"}],
    )

    before_invalid = len(parse_event_store(root))
    with pytest.raises(ESAAError) as missing:
        service.review_task("T-G07-E2E", actor="agent-qa", decision="approve")
    assert missing.value.code == "REVIEW_MODE_REQUIRED"
    assert len(parse_event_store(root)) == before_invalid

    with pytest.raises(ESAAError) as mismatch:
        service.review_task(
            "T-G07-E2E",
            actor="agent-qa",
            decision="request_changes",
            review_mode="security",
        )
    assert mismatch.value.code == "REVIEW_MODE_MISMATCH"
    assert len(parse_event_store(root)) == before_invalid

    service.review_task(
        "T-G07-E2E",
        actor="agent-qa",
        decision="request_changes",
        review_mode="governance",
    )
    service.complete_task(
        "T-G07-E2E",
        actor="agent-spec",
        checks=["Review changes addressed"],
    )
    approved = service.review_task(
        "T-G07-E2E",
        actor="agent-qa",
        decision="approve",
        review_mode="governance",
    )

    assert approved["task"]["status"] == "done"
    review_payloads = [
        event["payload"]
        for event in parse_event_store(root)
        if event["action"] == "review" and event["payload"]["task_id"] == "T-G07-E2E"
    ]
    assert [payload["review_mode"] for payload in review_payloads] == [
        "governance",
        "governance",
    ]


def test_g07_replay_and_lesson_context_contract(repo_root: Path) -> None:
    events = [
        make_event(
            1,
            actor="orchestrator",
            action="orchestrator.view.mutate",
            payload={
                "target": "lessons",
                "change": "seed_g07_lessons",
                "lessons": [
                    {
                        "lesson_id": "LES-G07-ACTIVE",
                        "status": "active",
                        "created_at": "2026-07-01T00:00:00Z",
                        "title": "Active governance lesson",
                        "mistake": "Missing typed review",
                        "rule": "Governance tasks require governance review",
                        "scope": {"task_types": ["governance"], "paths": ["docs/spec/**"]},
                        "enforcement": {"mode": "require_review_mode", "value": "governance"},
                    },
                    {
                        "lesson_id": "LES-G07-EXPERIMENTAL",
                        "status": "experimental",
                        "created_at": "2026-07-01T00:00:00Z",
                        "title": "Experimental governance lesson",
                        "mistake": "Missing note",
                        "rule": "Try a note",
                        "scope": {"task_types": ["governance"]},
                        "enforcement": {"mode": "require_note"},
                    },
                    {
                        "lesson_id": "LES-G07-SUPERSEDED",
                        "status": "superseded",
                        "created_at": "2026-07-01T00:00:00Z",
                        "title": "Old lesson",
                        "mistake": "Old rule",
                        "rule": "Do not apply",
                        "scope": {"task_types": ["governance"]},
                        "enforcement": {"mode": "warn"},
                    },
                ],
            },
        ),
        make_event(
            2,
            actor="orchestrator",
            action="task.create",
            payload={
                "task_id": "T-BASE",
                "task_kind": "spec",
                "title": "Base task",
                "status": "todo",
                "depends_on": [],
                "targets": ["docs/spec/base.md"],
                "outputs": {"files": ["docs/spec/base.md"]},
            },
        ),
        make_event(
            3,
            actor="orchestrator",
            action="task.create",
            payload={
                "task_id": "T-G07-REPLAY",
                "task_kind": "spec",
                "title": "Replay task",
                "status": "todo",
                "depends_on": [],
                "targets": ["docs/spec/replay.md"],
                "outputs": {"files": ["docs/spec/replay.md"]},
                "task_type": "governance",
                "acceptance_criteria": ["Replay keeps G07 fields"],
                "required_review_mode": "governance",
                "supersedes": ["T-BASE"],
            },
        ),
    ]

    roadmap, _, lessons_view = materialize(events)
    replay_task = next(task for task in roadmap["tasks"] if task["task_id"] == "T-G07-REPLAY")
    base_task = next(task for task in roadmap["tasks"] if task["task_id"] == "T-BASE")
    assert base_task["superseded_by"] == ["T-G07-REPLAY"]
    assert replay_task["task_type"] == "governance"
    assert replay_task["acceptance_criteria"] == ["Replay keeps G07 fields"]
    assert "required_review_mode" not in base_task
    assert "task_type" not in base_task

    contract = yaml.safe_load((repo_root / ".roadmap" / "AGENT_CONTRACT.yaml").read_text())
    schema = json.loads((repo_root / "src" / "esaa" / "templates" / "agent_result.schema.json").read_text())
    context = build_minimal_context(
        roadmap,
        {**replay_task, "status": "in_progress"},
        contract,
        schema,
        lessons=lessons_view["lessons"],
        issues=[],
    )

    assert context["task"]["supersedes"] == ["T-BASE"]
    assert context["task"].get("superseded_by", []) == []
    assert [lesson["lesson_id"] for lesson in context["lessons"]] == [
        "LES-G07-ACTIVE",
        "LES-G07-EXPERIMENTAL",
    ]
