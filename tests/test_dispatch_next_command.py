"""Executable dispatch examples, without invented runner or file permissions."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

from esaa.bootstrap import bootstrap_workspace
from esaa.cli import main
from esaa.dispatch import build_minimal_context
from esaa.service import ESAAService
from esaa.store import load_agent_contract, load_agent_result_schema, parse_event_store


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ESAAService:
    monkeypatch.delenv("ESAA_RUNNER_ID", raising=False)
    root = tmp_path / "workspace d'agua"
    bootstrap_workspace(root)
    service = ESAAService(root)
    service.init(force=True)
    return service


def _validate(context: dict, root: Path) -> None:
    for schema in (load_agent_result_schema(root), context["schema_slice"]):
        jsonschema.validate(context["example_envelope"], schema)
    argv = context["next_command_argv"]
    if argv is not None:
        assert shlex.split(context["next_command"]) == argv
        assert argv[:5] == ["python", "-m", "esaa", "--root", str(root)]
        for marker in ("...", "…", "<", ">", "TODO"):
            assert marker not in context["next_command"]
            assert all(marker not in arg for arg in argv)


def _execute(context: dict, root: Path) -> dict:
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    before = (root / ".roadmap/activity.jsonl").read_bytes()
    result = subprocess.run(
        context["next_command_argv"] + ["--dry-run"],
        input=context.get("example_stdin"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output = json.loads(result.stdout)
    assert output["status"] == "dry_run"
    assert (root / ".roadmap/activity.jsonl").read_bytes() == before
    return output


@pytest.mark.parametrize("kind", ["spec", "impl", "qa"])
@pytest.mark.parametrize("status", ["todo", "in_progress", "review", "done"])
def test_commands_execute_and_envelopes_validate(workspace: ESAAService, kind: str, status: str) -> None:
    svc = workspace
    task_id = f"T-{kind}"
    output = {"spec": "docs/spec/a.md", "impl": "src/a.py", "qa": "docs/qa/a.md"}[kind]
    svc.create_task(task_id, kind, "Exemplo", outputs=[output], required_review_mode="functional")
    # The assignee can differ from the kind default; complete must preserve it.
    assignee = "implementation-specialist"
    if status != "todo":
        svc.claim_task(task_id, assignee)
    if status in {"review", "done"}:
        svc.complete_task(task_id, assignee, checks=["Verificado"])
    if status == "done":
        svc.review_task(task_id, "agent-qa", "approve", review_mode="functional")
    before = len(parse_event_store(svc.root))
    context = svc.dispatch_context(task_id)
    assert len(parse_event_store(svc.root)) == before
    _validate(context, svc.root)
    if status == "done":
        assert context["next_command"] is None
        assert context["next_command_argv"] is None
        assert context["example_envelope"]["activity_event"]["action"] == "issue.report"
        return
    argv = context["next_command_argv"]
    assert "--runner" not in argv
    expected_actor = assignee if status == "in_progress" else f"agent-{'qa' if status == 'review' else kind}"
    assert argv[argv.index("--actor") + 1] == expected_actor
    if status == "in_progress":
        # Empty updates are deliberately safe even when an output already exists.
        path = svc.root / output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("existing content\n", encoding="utf-8")
        assert context["example_stdin"] == "[]"
        assert context["example_envelope"]["file_updates"] == []
    _execute(context, svc.root)
    if status == "in_progress":
        assert path.read_text(encoding="utf-8") == "existing content\n"


def test_swarm_resolution_and_explicit_runner(workspace: ESAAService, capsys: pytest.CaptureFixture) -> None:
    svc = workspace
    path = svc.root / ".roadmap/agents_swarm.yaml"
    swarm = yaml.safe_load(path.read_text(encoding="utf-8"))
    swarm["resolution"]["by_task_kind"]["impl"]["agent"] = "custom-impl"
    swarm["resolution"]["by_task_kind"]["qa"]["agent"] = "quality-team"
    swarm["agents"]["quality-team"] = {"role": "qa"}
    path.write_text(yaml.safe_dump(swarm), encoding="utf-8")
    svc.create_task("T-CUSTOM", "impl", "Custom")
    assert main(["--root", str(svc.root), "--runner", "codex", "dispatch-context", "T-CUSTOM"]) == 0
    context = json.loads(capsys.readouterr().out)
    _validate(context, svc.root)
    assert context["next_command_argv"][-1] == "custom-impl"
    assert context["next_command_argv"][5:7] == ["--runner", "codex"]
    assert "runner" not in context["example_envelope"]
    _execute(context, svc.root)
    svc.claim_task("T-CUSTOM", "custom-impl")
    svc.complete_task("T-CUSTOM", "custom-impl", ["Verificado"])
    context = svc.dispatch_context("T-CUSTOM")
    assert context["next_command_argv"][-3:] == ["quality-team", "--decision", "approve"]
    _execute(context, svc.root)


def test_without_outputs_omits_stdin(workspace: ESAAService) -> None:
    svc = workspace
    svc.create_task("T-NO-OUTPUT", "impl", "Sem arquivos")
    svc.claim_task("T-NO-OUTPUT", "agent-impl")
    context = svc.dispatch_context("T-NO-OUTPUT")
    assert "example_stdin" not in context
    assert "--file-updates" not in context["next_command_argv"]
    _validate(context, svc.root)
    _execute(context, svc.root)


def test_hotfix_uses_two_checks_and_links(workspace: ESAAService) -> None:
    svc = workspace
    svc.create_task("T-BASE", "impl", "Base")
    svc.claim_task("T-BASE", "agent-impl")
    svc.complete_task("T-BASE", "agent-impl", ["Verificado"])
    svc.review_task("T-BASE", "agent-qa", "approve")
    svc.report_issue("T-BASE", "agent-qa", "ISS-BASE", "low", "Falha", "Sintoma", ["Reproducao"])
    svc.create_hotfix("ISS-BASE", "T-BASE", scope_patch=["src/fix.py"], outputs=["src/fix.py"])
    svc.claim_task("HF-ISS-BASE", "agent-impl")
    context = svc.dispatch_context("HF-ISS-BASE")
    _validate(context, svc.root)
    event = context["example_envelope"]["activity_event"]
    assert len(event["verification"]["checks"]) == 2
    assert event["issue_id"] == "ISS-BASE"
    assert event["fixes"] == "T-BASE"
    _execute(context, svc.root)


def test_missing_assignee_never_invents_actor(workspace: ESAAService) -> None:
    svc = workspace
    task = {"task_id": "T-INVALID", "status": "in_progress", "task_kind": "impl"}
    context = build_minimal_context(
        {"meta": {}, "tasks": [task]},
        task,
        load_agent_contract(svc.root),
        load_agent_result_schema(svc.root),
        root=svc.root,
    )
    _validate(context, svc.root)
    assert context["next_command"] is None
    assert "assigned_to" in context["next_command_reason"]
    assert context["example_envelope"]["activity_event"]["action"] == "issue.report"


def test_context_growth_stays_below_budget(workspace: ESAAService) -> None:
    svc = workspace
    svc.create_task("T-SIZE", "impl", "Tamanho", outputs=["src/a.py"])
    svc.claim_task("T-SIZE", "agent-impl")
    context = svc.dispatch_context("T-SIZE")
    added = {key: value for key, value in context.items() if key.startswith(("next_command", "example_"))}
    assert len(json.dumps(added, indent=2, ensure_ascii=False).encode("utf-8")) <= 1536


def test_packaged_guide_is_smaller_and_explains_examples(repo_root: Path) -> None:
    data = (repo_root / "src/esaa/workspace/AGENTS.md").read_bytes()
    assert len(data) < 4052  # Baseline before AUD-O2-020.
    text = data.decode("utf-8")
    for term in ("next_command_argv", "example_envelope", "example_stdin", "[]", "reject", "PARCER"):
        assert term in text
