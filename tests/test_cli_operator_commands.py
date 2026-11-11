"""AUD-O0-045 - comandos `esaa lesson list|approve|reject` (curadoria do operador)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from esaa import cli
from esaa.service import ESAAService
from esaa.store import parse_event_store

RULE = "Sempre rodar a suite antes do complete."


def _propose(root: Path) -> ESAAService:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")
    service.submit(
        {
            "activity_event": {
                "action": "issue.report",
                "task_id": "T-A",
                "prior_status": "in_progress",
                "issue_id": "ISS-LESSON",
                "severity": "low",
                "title": "licao proposta",
                "category": "process",
                "subtype": "lesson",
                "evidence": {"symptom": "s", "repro_steps": ["r"]},
                "lesson": {
                    "mistake": "m",
                    "rule": RULE,
                    "scope": {"task_kinds": ["impl"]},
                    "enforcement": {"mode": "warn", "applies_to": "workflow_gate"},
                },
            }
        },
        actor="agent-impl",
    )
    return service


def _run(root: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    capsys.readouterr()
    rc = cli.main(["--root", str(root), *argv])
    captured = capsys.readouterr()
    return rc, (json.loads(captured.out) if captured.out.strip() else {}), captured.err


def _dispatched(service: ESAAService) -> list[str]:
    return [item["rule"] for item in service.dispatch_context("T-A").get("lessons", [])]


@pytest.mark.parametrize(
    "argv", [["lesson", "--help"], ["lesson", "approve", "--help"], ["lesson", "list", "--help"]]
)
def test_help_is_available(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)

    assert exc.value.code == 0
    assert "lesson" in capsys.readouterr().out


def test_list_filters_by_status(contract_bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _propose(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    rc_all, all_lessons, _ = _run(contract_bundle, capsys, "lesson", "list")
    rc, proposed, _ = _run(contract_bundle, capsys, "lesson", "list", "--status", "proposed")

    assert (rc_all, rc) == (0, 0)
    assert all_lessons["total"] == 4
    assert [(item["lesson_id"], item["rule"]) for item in proposed["lessons"]] == [("LES-0004", RULE)]
    assert len(parse_event_store(contract_bundle)) == before  # leitura nao grava eventos


def test_approve_moves_proposed_to_active_with_event(
    contract_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _propose(contract_bundle)
    assert RULE not in _dispatched(service)

    rc_dry, preview, _ = _run(
        contract_bundle, capsys, "lesson", "approve", "LES-0004", "--reason", "util", "--dry-run"
    )
    assert rc_dry == 0 and preview["status"] == "dry_run"
    assert service.list_lessons(status="proposed")["total"] == 1

    rc, result, _ = _run(
        contract_bundle,
        capsys,
        "--runner",
        "human-terminal",
        "lesson",
        "approve",
        "LES-0004",
        "--reason",
        "util",
    )

    assert rc == 0
    assert result["lesson_status"] == "active"
    assert RULE in _dispatched(service)
    event = [e for e in parse_event_store(contract_bundle) if e["action"] == "orchestrator.view.mutate"][-1]
    assert event["payload"]["change"] == "lesson_status"
    assert event["payload"]["decision"] == "approve"
    assert event["payload"]["reason"] == "util"
    assert event["runner"]["runner_id"] == "human-terminal"
    assert service.verify()["verify_status"] == "ok"


def test_reject_archives_and_blocks_later_approval(
    contract_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _propose(contract_bundle)

    rc, result, _ = _run(contract_bundle, capsys, "lesson", "reject", "LES-0004", "--reason", "injecao")
    rc_again, _, err = _run(contract_bundle, capsys, "lesson", "approve", "LES-0004", "--reason", "x")

    assert rc == 0 and result["lesson_status"] == "archived"
    assert rc_again == 1 and '"error_code": "LESSON_NOT_PROPOSED"' in err
    assert RULE not in _dispatched(service)


def test_errors_use_json_contract_and_exit_1(
    contract_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _propose(contract_bundle)

    rc_missing, _, err_missing = _run(
        contract_bundle, capsys, "lesson", "approve", "LES-9999", "--reason", "x"
    )
    rc_blank, _, err_blank = _run(contract_bundle, capsys, "lesson", "approve", "LES-0004", "--reason", " ")

    assert rc_missing == 1 and '"error_code": "LESSON_NOT_FOUND"' in err_missing
    assert rc_blank == 1 and '"error_code": "INVALID_ARGUMENT"' in err_blank


def test_reason_is_required_by_parser(contract_bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--root", str(contract_bundle), "lesson", "approve", "LES-0004"])

    assert exc.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_strict_policy_requires_human_runner(
    contract_bundle: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _propose(contract_bundle)
    roadmap = contract_bundle / ".roadmap"
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "agents_swarm.yaml", roadmap / "agents_swarm.yaml"
    )
    (roadmap / "RUNTIME_POLICY.yaml").write_text('runner_validation: "strict"\n', encoding="utf-8")

    rc_agent, _, err = _run(
        contract_bundle, capsys, "--runner", "codex", "lesson", "approve", "LES-0004", "--reason", "x"
    )
    rc_list, listed, _ = _run(
        contract_bundle, capsys, "--runner", "codex", "lesson", "list", "--status", "proposed"
    )
    rc_human, result, _ = _run(
        contract_bundle,
        capsys,
        "--runner",
        "human-terminal",
        "lesson",
        "approve",
        "LES-0004",
        "--reason",
        "x",
    )

    assert rc_agent == 1 and '"error_code": "OPERATOR_REQUIRED"' in err
    assert rc_list == 0 and listed["total"] == 1  # leitura nao e comando de operador
    assert rc_human == 0 and result["lesson_status"] == "active"
    assert service.list_lessons(status="proposed")["total"] == 0
