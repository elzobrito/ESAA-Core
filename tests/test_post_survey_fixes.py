from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import esaa.submission as submission_module
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _copy_runtime_files(root: Path, repo_root: Path) -> None:
    roadmap = root / ".roadmap"
    roadmap.mkdir(parents=True, exist_ok=True)
    for name in (
        "AGENT_CONTRACT.yaml",
        "ORCHESTRATOR_CONTRACT.yaml",
        "agent_result.schema.json",
        "roadmap.schema.json",
        "issues.schema.json",
        "lessons.schema.json",
        "RUNTIME_POLICY.yaml",
        "agents_swarm.yaml",
    ):
        source = repo_root / ".roadmap" / name
        if source.exists():
            shutil.copy2(source, roadmap / name)


def _complete_seed_task(
    svc: ESAAService,
    task_id: str,
    actor: str,
    output: str,
    reviewer: str | None = None,
) -> None:
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}},
        actor=actor,
    )
    svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": task_id,
                "prior_status": "in_progress",
                "verification": {"checks": ["ok"]},
            },
            "file_updates": [{"path": output, "content": "ok\n"}],
        },
        actor=actor,
    )
    svc.submit(
        {
            "activity_event": {
                "action": "review",
                "task_id": task_id,
                "prior_status": "review",
                "decision": "approve",
                "tasks": [task_id],
            }
        },
        actor=reviewer or actor,
    )


def test_file_effect_can_recover_after_final_commit_failure(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    def fail_commit(_root: Path, _staged: list[dict]) -> None:
        raise RuntimeError("simulated final file failure")

    monkeypatch.setattr(submission_module, "commit_staged", fail_commit)
    with pytest.raises(RuntimeError, match="simulated final file failure"):
        svc.submit(
            {
                "activity_event": {
                    "action": "complete",
                    "task_id": "T-1000",
                    "prior_status": "in_progress",
                    "verification": {"checks": ["ok"]},
                },
                "file_updates": [{"path": "docs/spec/T-1000.md", "content": "recover me\n"}],
            },
            actor="agent-spec",
        )

    events = parse_event_store(contract_bundle)
    assert sum(1 for event in events if event["action"] == "complete") == 1
    assert sum(1 for event in events if event["action"] == "orchestrator.file.write") == 1
    final = contract_bundle / "docs/spec/T-1000.md"
    assert not final.exists()

    recovered = svc.recover_file_effects()
    assert recovered["files_recovered"] == 1
    assert final.read_text(encoding="utf-8") == "recover me\n"
    assert svc.recover_file_effects()["files_recovered"] == 0


def test_create_hotfix_rejects_orphan_request(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    with pytest.raises(ESAAError) as exc:
        svc.create_hotfix(issue_id="ISS-NOPE", fixes="TASK-NOPE", scope_patch=["src/hotfix/"])

    assert exc.value.code == "HOTFIX_TARGET_NOT_FOUND"
    assert not any(event["action"] == "hotfix.create" for event in parse_event_store(contract_bundle))


def test_issue_report_command_preserves_done_prior_status(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _complete_seed_task(svc, "T-1000", "agent-spec", "docs/spec/T-1000.md")

    svc.report_issue(
        "T-1000",
        actor="agent-qa",
        issue_id="ISS-DONE",
        severity="high",
        title="Done task issue",
        symptom="problem after done",
        repro_steps=["inspect done task"],
    )

    issue_event = [
        event for event in parse_event_store(contract_bundle) if event["action"] == "issue.report"
    ][-1]
    assert issue_event["payload"]["prior_status"] == "done"
    assert svc.task_state("T-1000")["task"]["status"] == "done"


def test_activity_clear_reseeds_baseline_lessons(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    result = svc.clear_activity(force=True)

    lessons = json.loads((contract_bundle / ".roadmap" / "lessons.json").read_text(encoding="utf-8"))
    ids = {lesson["lesson_id"] for lesson in lessons["lessons"]}
    assert {"LES-0001", "LES-0002", "LES-0003"}.issubset(ids)
    assert result["verify_status"] == "ok"
    assert result["last_event_seq"] > 0


def test_run_consumes_late_plugin_task(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime_files(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _complete_seed_task(svc, "T-1000", "agent-spec", "docs/spec/T-1000.md", reviewer="agent-qa")
    _complete_seed_task(svc, "T-1010", "agent-impl", "src/T-1010.txt", reviewer="agent-qa")
    _complete_seed_task(svc, "T-1020", "agent-qa", "docs/qa/T-1020.md", reviewer="agent-qa")

    plugin = {
        "meta": {
            "schema_version": "0.4.1",
            "esaa_version": "0.4.x",
            "immutable_done": True,
            "master_correlation_id": None,
            "run": {
                "run_id": None,
                "status": "initialized",
                "last_event_seq": 0,
                "projection_hash_sha256": "0" * 64,
                "verify_status": "unknown",
            },
            "updated_at": "2026-05-23T00:00:00Z",
        },
        "project": {"name": "late-plugin", "audit_scope": "late plugin test"},
        "tasks": [
            {
                "task_id": "PLG-LATE-1",
                "task_kind": "spec",
                "title": "Late plugin task",
                "description": "Task added after init",
                "status": "todo",
                "depends_on": [],
                "targets": ["late"],
                "outputs": {"files": ["docs/spec/PLG-LATE-1.md"]},
                "immutability": {"done_is_immutable": True},
            }
        ],
        "indexes": {"by_status": {"todo": 1}, "by_kind": {"spec": 1}},
    }
    (tmp_path / ".roadmap" / "roadmap.late.json").write_text(json.dumps(plugin), encoding="utf-8")

    eligible_ids = {task["task_id"] for task in svc.eligible()["eligible"]}
    assert "PLG-LATE-1" in eligible_ids

    result = svc.run(steps=1)
    assert result["steps_executed"] == 1
    events = parse_event_store(tmp_path)
    assert any(
        event["action"] == "task.create" and event["payload"].get("task_id") == "PLG-LATE-1"
        for event in events
    )
    assert any(
        event["action"] == "claim" and event["payload"].get("task_id") == "PLG-LATE-1" for event in events
    )


def test_repo_policy_allows_independent_agent_qa_review(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime_files(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": "T-1000",
                "prior_status": "in_progress",
                "verification": {"checks": ["ok"]},
            },
            "file_updates": [{"path": "docs/spec/T-1000.md", "content": "ok\n"}],
        },
        actor="agent-spec",
    )

    result = svc.submit(
        {
            "activity_event": {
                "action": "review",
                "task_id": "T-1000",
                "prior_status": "review",
                "decision": "approve",
                "tasks": ["T-1000"],
            }
        },
        actor="agent-qa",
    )
    assert result["status"] == "accepted"


def test_runner_metrics_dry_run_response_is_unambiguous(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    before = parse_event_store(contract_bundle)

    result = svc.record_runner_metrics(
        {
            "task_id": "T-1000",
            "actor": "agent-spec",
            "runner_id": "codex-local",
            "runner_kind": "codex",
            "model": "gpt-5",
            "command_surface": "codex-desktop",
            "latency_ms": 12,
            "input_tokens": 3,
            "output_tokens": 4,
            "status": "success",
        },
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["would_append_events"] >= 1
    assert len(parse_event_store(contract_bundle)) == len(before)
