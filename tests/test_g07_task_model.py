from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _workspace(tmp_path: Path, repo_root: Path) -> Path:
    root = tmp_path / "workspace"
    roadmap = root / ".roadmap"
    roadmap.mkdir(parents=True)
    for name in ("AGENT_CONTRACT.yaml", "agent_result.schema.json", "roadmap.schema.json"):
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


def _task(root: Path, task_id: str) -> dict:
    return ESAAService(root).task_state(task_id)["task"]


def test_task_create_preserves_g07_fields_and_derives_superseded_by(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    service = ESAAService(root)

    service.create_task(
        "T-G07-A",
        task_kind="spec",
        title="G07 task",
        outputs=["docs/spec/g07-a.md"],
        task_type="governance",
        acceptance_criteria=["AC one", "AC two"],
        required_review_mode="governance",
        supersedes=["T-1000"],
    )
    service.create_task(
        "T-G07-B",
        task_kind="spec",
        title="G07 follow-up",
        outputs=["docs/spec/g07-b.md"],
        supersedes=["T-1000"],
    )

    created = _task(root, "T-G07-A")
    assert created["task_type"] == "governance"
    assert created["acceptance_criteria"] == ["AC one", "AC two"]
    assert created["required_review_mode"] == "governance"
    assert created["supersedes"] == ["T-1000"]

    superseded = _task(root, "T-1000")
    assert superseded["status"] == "todo"
    assert superseded["superseded_by"] == ["T-G07-A", "T-G07-B"]


def test_task_create_rejects_invalid_supersedes_before_append(tmp_path: Path, repo_root: Path) -> None:
    root = _workspace(tmp_path, repo_root)
    service = ESAAService(root)

    before = len(parse_event_store(root))
    cases = [
        {"supersedes": ["T-MISSING"]},
        {"supersedes": ["T-SELF"], "task_id": "T-SELF"},
        {"supersedes": ["T-1000", "T-1000"]},
    ]

    for index, case in enumerate(cases):
        task_id = case.get("task_id", f"T-BAD-{index}")
        try:
            service.create_task(
                task_id,
                task_kind="spec",
                title="Invalid supersedes",
                outputs=[f"docs/spec/{task_id}.md"],
                supersedes=case["supersedes"],
            )
        except ESAAError:
            pass
        else:
            raise AssertionError(f"expected ESAAError for {case}")
        assert len(parse_event_store(root)) == before


def test_task_create_rejects_invalid_g07_task_fields_before_append(
    tmp_path: Path, repo_root: Path
) -> None:
    root = _workspace(tmp_path, repo_root)
    service = ESAAService(root)

    before = len(parse_event_store(root))
    invalid_calls = [
        {"task_type": "research"},
        {"acceptance_criteria": [""]},
        {"required_review_mode": "audit"},
    ]

    for index, kwargs in enumerate(invalid_calls):
        try:
            service.create_task(
                f"T-BAD-FIELD-{index}",
                task_kind="spec",
                title="Invalid G07 field",
                outputs=[f"docs/spec/bad-field-{index}.md"],
                **kwargs,
            )
        except ESAAError:
            pass
        else:
            raise AssertionError(f"expected ESAAError for {kwargs}")
        assert len(parse_event_store(root)) == before


def test_task_create_cli_accepts_g07_flags(tmp_path: Path, repo_root: Path) -> None:
    root = _workspace(tmp_path, repo_root)

    result = _run_cli(
        root,
        "task",
        "create",
        "T-G07-CLI",
        "--kind",
        "spec",
        "--title",
        "CLI G07 task",
        "--output",
        "docs/spec/g07-cli.md",
        "--task-type",
        "governance",
        "--acceptance-criterion",
        "CLI criterion one",
        "--acceptance-criterion",
        "CLI criterion two",
        "--required-review-mode",
        "governance",
        "--supersedes",
        "T-1000",
    )

    assert result["status"] == "accepted"
    created = _task(root, "T-G07-CLI")
    assert created["task_type"] == "governance"
    assert created["acceptance_criteria"] == ["CLI criterion one", "CLI criterion two"]
    assert created["required_review_mode"] == "governance"
    assert created["supersedes"] == ["T-1000"]
    assert _task(root, "T-1000")["superseded_by"] == ["T-G07-CLI"]
