from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from esaa.cli import main
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _run_cli_error(root: Path, *args: str) -> dict:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = main(["--root", str(root), *args])
    assert code == 1
    return json.loads(stderr.getvalue())


def test_cli_claim_complete_review_drive_state_machine_without_adapter(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)

    claim = _run_cli(contract_bundle, "claim", "T-1000", "--actor", "agent-spec")
    assert claim["action"] == "claim"
    assert claim["task"]["status"] == "in_progress"

    state = _run_cli(contract_bundle, "state", "T-1000")
    assert state["task"]["assigned_to"] == "agent-spec"
    assert state["expected_action"] == "complete"

    context = _run_cli(contract_bundle, "dispatch-context", "T-1000")
    assert context["expected_action"] == "complete"
    assert context["task"]["task_id"] == "T-1000"

    updates = contract_bundle / "updates.json"
    updates.write_text(
        json.dumps([{"path": "docs/spec/T-1000.md", "content": "# Deterministic\n"}]),
        encoding="utf-8",
    )
    complete = _run_cli(
        contract_bundle,
        "complete",
        "T-1000",
        "--actor",
        "agent-spec",
        "--check",
        "deterministic-output",
        "--file-updates",
        str(updates),
    )
    assert complete["action"] == "complete"
    assert complete["task"]["status"] == "review"
    assert (contract_bundle / "docs/spec/T-1000.md").read_text(encoding="utf-8") == "# Deterministic\n"

    review = _run_cli(
        contract_bundle,
        "review",
        "T-1000",
        "--actor",
        "agent-spec",
        "--decision",
        "approve",
    )
    assert review["action"] == "review"
    assert review["task"]["status"] == "done"

    events = parse_event_store(contract_bundle)
    assert [event["action"] for event in events if event["actor"] == "agent-spec"] == [
        "claim",
        "complete",
        "review",
    ]


def test_cli_can_speak_transition_messages(contract_bundle: Path, monkeypatch) -> None:
    ESAAService(contract_bundle).init(force=True)

    calls = []

    def fake_transition(status: str):
        calls.append(status)
        messages = {"in_progress": "Task in progress", "review": "Task review", "done": "Task done"}
        return {"status": "played", "backend": "test", "message": messages[status]}

    monkeypatch.setattr("esaa.task_admin.play_transition_message", fake_transition)

    claim = _run_cli(
        contract_bundle,
        "claim",
        "T-1000",
        "--actor",
        "agent-spec",
        "--notify-transition",
    )
    assert claim["task"]["status"] == "in_progress"
    assert claim["transition_notification"]["message"] == "Task in progress"

    updates = contract_bundle / "updates.json"
    updates.write_text(
        json.dumps([{"path": "docs/spec/T-1000.md", "content": "# Deterministic\n"}]),
        encoding="utf-8",
    )
    complete = _run_cli(
        contract_bundle,
        "complete",
        "T-1000",
        "--actor",
        "agent-spec",
        "--check",
        "deterministic-output",
        "--file-updates",
        str(updates),
        "--notify-transition",
    )
    assert complete["task"]["status"] == "review"
    assert complete["transition_notification"]["message"] == "Task review"

    review = _run_cli(
        contract_bundle,
        "review",
        "T-1000",
        "--actor",
        "agent-spec",
        "--decision",
        "approve",
        "--notify-completion",
    )
    assert review["task"]["status"] == "done"
    assert review["completion_notification"]["message"] == "Task done"
    assert calls == ["in_progress", "review", "done"]


def test_cli_reject_issue_hotfix_and_resolve_are_deterministic_orchestrator_commands(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)

    rejected = _run_cli(
        contract_bundle,
        "reject",
        "T-1000",
        "--error-code",
        "MISSING_VERIFICATION",
        "--source-action",
        "complete",
        "--message",
        "missing checks",
    )
    assert rejected["action"] == "output.rejected"

    updates = contract_bundle / "hotfix-target-updates.json"
    updates.write_text(
        json.dumps([{"path": "docs/spec/T-1000.md", "content": "# Done target\n"}]),
        encoding="utf-8",
    )
    _run_cli(contract_bundle, "claim", "T-1000", "--actor", "agent-spec")
    _run_cli(
        contract_bundle,
        "complete",
        "T-1000",
        "--actor",
        "agent-spec",
        "--check",
        "target complete",
        "--file-updates",
        str(updates),
    )
    _run_cli(contract_bundle, "review", "T-1000", "--actor", "agent-spec", "--decision", "approve")

    issue = _run_cli(
        contract_bundle,
        "issue",
        "report",
        "T-1000",
        "--actor",
        "harness",
        "--issue-id",
        "ISS-CLI",
        "--severity",
        "medium",
        "--title",
        "CLI issue",
        "--symptom",
        "deterministic issue command",
        "--repro-step",
        "run issue report",
    )
    assert issue["action"] == "issue.report"

    hotfix = _run_cli(
        contract_bundle,
        "hotfix",
        "create",
        "--issue-id",
        "ISS-CLI",
        "--fixes",
        "T-1000",
        "--scope-patch",
        "src/hotfix/",
    )
    assert hotfix["action"] == "hotfix.create"
    assert hotfix["task_id"] == "HF-ISS-CLI"

    resolved = _run_cli(
        contract_bundle,
        "issue",
        "resolve",
        "--issue-id",
        "ISS-CLI",
        "--hotfix-task-id",
        "HF-ISS-CLI",
    )
    assert resolved["action"] == "issue.resolve"

    actions = [event["action"] for event in parse_event_store(contract_bundle)]
    assert "output.rejected" in actions
    assert "issue.report" in actions
    assert "hotfix.create" in actions
    assert "issue.resolve" in actions


def test_cli_task_create_adds_task_through_orchestrator_command(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)

    created = _run_cli(
        contract_bundle,
        "task",
        "create",
        "REAL-CLI",
        "--kind",
        "qa",
        "--title",
        "Real CLI task",
        "--description",
        "Created through the public deterministic task command.",
        "--output",
        "docs/qa/REAL-CLI.md",
        "--target",
        "cli-task-create",
        "--depends-on",
        "T-1000",
    )

    assert created["action"] == "task.create"
    assert created["task_id"] == "REAL-CLI"
    state = _run_cli(contract_bundle, "state", "REAL-CLI")
    assert state["source"] == "event_store"
    assert state["task"]["task_kind"] == "qa"
    assert state["task"]["depends_on"] == ["T-1000"]
    assert state["task"]["outputs"]["files"] == ["docs/qa/REAL-CLI.md"]
    assert state["verify_status"] == "ok"

    roadmap = json.loads((contract_bundle / ".roadmap" / "roadmap.json").read_text(encoding="utf-8"))
    schema = json.loads((contract_bundle / ".roadmap" / "roadmap.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(roadmap)


def test_cli_task_create_rejects_duplicate_task_id(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)

    _run_cli(
        contract_bundle,
        "task",
        "create",
        "REAL-CLI",
        "--kind",
        "spec",
        "--title",
        "Real CLI task",
        "--output",
        "docs/spec/REAL-CLI.md",
    )

    error = _run_cli_error(
        contract_bundle,
        "task",
        "create",
        "REAL-CLI",
        "--kind",
        "spec",
        "--title",
        "Real CLI task again",
        "--output",
        "docs/spec/REAL-CLI-2.md",
    )
    assert error["error_code"] == "DUPLICATE_TASK"


def test_cli_task_create_rejects_values_that_break_roadmap_schema(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)

    error = _run_cli_error(
        contract_bundle,
        "task",
        "create",
        "REAL-BAD",
        "--kind",
        "qa",
        "--title",
        "Real bad task",
        "--output",
        "",
    )

    assert error["error_code"] == "SCHEMA_INVALID"
    assert parse_event_store(contract_bundle)[-1]["action"] == "verify.ok"


def test_cli_activity_clear_requires_force_and_reprojects_empty_state(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True)
    before = parse_event_store(contract_bundle)
    assert before

    error = _run_cli_error(contract_bundle, "activity", "clear")
    assert error["error_code"] == "CLEAR_REQUIRES_FORCE"
    assert parse_event_store(contract_bundle)

    cleared = _run_cli(contract_bundle, "activity", "clear", "--force")

    assert cleared["status"] == "cleared"
    assert cleared["events_removed"] == len(before)
    assert cleared["last_event_seq"] == 3
    assert cleared["verify_status"] == "ok"
    events_after_clear = parse_event_store(contract_bundle)
    assert [event["action"] for event in events_after_clear] == [
        "orchestrator.view.mutate",
        "verify.start",
        "verify.ok",
    ]
    assert (contract_bundle / ".roadmap" / "activity.jsonl").read_text(encoding="utf-8").strip()

    backup = contract_bundle / cleared["backup_path"]
    assert backup.exists()
    assert backup.read_text(encoding="utf-8").strip()
