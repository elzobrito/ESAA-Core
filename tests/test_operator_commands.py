"""AUD-O0-040 (GOV-03/GOV-04/SEC-02) - comandos de operador, trilha do activity clear e impersonacao."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from esaa import cli
from esaa.errors import ESAAError
from esaa.provenance import ENV_RUNNER_ID
from esaa.reject_codes import ALL_CODES, OPERATOR_REQUIRED
from esaa.runtime_policy import require_operator_runner, runner_kind
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _workspace(root: Path, repo_root: Path, *, strict: bool) -> ESAAService:
    roadmap = root / ".roadmap"
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "agents_swarm.yaml", roadmap / "agents_swarm.yaml"
    )
    mode = "strict" if strict else "permissive"
    (roadmap / "RUNTIME_POLICY.yaml").write_text(
        f'review_authorization: "qa_role"\nrunner_validation: "{mode}"\n', encoding="utf-8"
    )
    return ESAAService(root)


def _seed(service: ESAAService) -> None:
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])


def _operator_calls(service: ESAAService) -> dict[str, Any]:
    return {
        "task create": lambda: service.create_task(
            "T-NEW", "impl", "nova", outputs=["src/n.txt"], dry_run=True
        ),
        "task amend": lambda: service.amend_task("T-A", title="novo titulo", dry_run=True),
        "reject": lambda: service.reject_output("T-A", "X", "complete", "m", dry_run=True),
        "issue resolve": lambda: service.resolve_issue("ISS-NOPE", dry_run=True),
        "hotfix create": lambda: service.create_hotfix("ISS-NOPE", "T-A", dry_run=True),
        "activity clear": lambda: service.clear_activity(force=True, dry_run=True),
        "task limits set": lambda: service.set_task_limits(
            "T-A", {"max_file_updates": 4}, reason="r", authorized_by="op", dry_run=True
        ),
        "lesson decision": lambda: service.decide_lesson("LES-0001", "approve", reason="r", dry_run=True),
    }


def test_code_registered() -> None:
    assert OPERATOR_REQUIRED in ALL_CODES


def test_runner_kind_reads_swarm_registry(contract_bundle: Path, repo_root: Path) -> None:
    _workspace(contract_bundle, repo_root, strict=True)

    assert runner_kind(contract_bundle, "human-terminal") == "human"
    assert runner_kind(contract_bundle, "codex") == "llm-agent"
    assert runner_kind(contract_bundle, "nao-registrado") is None


def test_strict_blocks_every_operator_command_for_agent_runner(
    contract_bundle: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _workspace(contract_bundle, repo_root, strict=True)
    monkeypatch.setenv(ENV_RUNNER_ID, "human-terminal")
    _seed(service)
    before = len(parse_event_store(contract_bundle))

    for runner in ("codex", "nao-registrado"):
        monkeypatch.setenv(ENV_RUNNER_ID, runner)
        for command, call in _operator_calls(service).items():
            with pytest.raises(ESAAError) as exc:
                call()
            assert exc.value.code == OPERATOR_REQUIRED, command
            assert command in exc.value.message
            assert runner in exc.value.message

    assert len(parse_event_store(contract_bundle)) == before


def test_strict_blocks_default_unattended_runner(
    contract_bundle: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitir --runner cai em 'unattended' (kind=unknown), que nao e humano."""
    _workspace(contract_bundle, repo_root, strict=True)
    monkeypatch.delenv(ENV_RUNNER_ID, raising=False)

    with pytest.raises(ESAAError) as exc:
        require_operator_runner(contract_bundle, "reject")

    assert exc.value.code == OPERATOR_REQUIRED


def test_strict_allows_human_runner(
    contract_bundle: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _workspace(contract_bundle, repo_root, strict=True)
    monkeypatch.setenv(ENV_RUNNER_ID, "human-terminal")
    _seed(service)

    result = service.reject_output("T-A", "X", "complete", "m")

    assert result["status"] == "accepted"
    assert service.verify()["verify_status"] == "ok"


def test_strict_does_not_gate_agent_transitions(
    contract_bundle: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _workspace(contract_bundle, repo_root, strict=True)
    monkeypatch.setenv(ENV_RUNNER_ID, "human-terminal")
    _seed(service)
    monkeypatch.setenv(ENV_RUNNER_ID, "codex")

    assert service.claim_task("T-A", actor="agent-impl")["status"] == "accepted"
    assert service.eligible()["eligible_count"] == 0
    assert service.task_state("T-A")["task"]["status"] == "in_progress"


def test_permissive_keeps_previous_behaviour(
    contract_bundle: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _workspace(contract_bundle, repo_root, strict=False)
    monkeypatch.setenv(ENV_RUNNER_ID, "codex")
    _seed(service)

    assert service.reject_output("T-A", "X", "complete", "m")["status"] == "accepted"
    assert service.amend_task("T-A", title="novo")["status"] == "accepted"
    assert service.clear_activity(force=True)["status"] == "cleared"


def test_cli_reports_operator_required(
    contract_bundle: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = _workspace(contract_bundle, repo_root, strict=True)
    monkeypatch.setenv(ENV_RUNNER_ID, "human-terminal")
    _seed(service)
    capsys.readouterr()
    root = str(contract_bundle)

    rc_reject = cli.main(
        [
            "--root",
            root,
            "--runner",
            "codex",
            "reject",
            "T-A",
            "--error-code",
            "X",
            "--source-action",
            "complete",
            "--message",
            "m",
        ]
    )
    rc_clear = cli.main(["--root", root, "--runner", "codex", "activity", "clear", "--force"])

    assert (rc_reject, rc_clear) == (1, 1)
    assert capsys.readouterr().err.count('"error_code": "OPERATOR_REQUIRED"') == 2
    assert service.task_state("T-A")["task"]["status"] == "todo"


def test_activity_clear_records_previous_log(contract_bundle: Path, repo_root: Path) -> None:
    service = _workspace(contract_bundle, repo_root, strict=False)
    _seed(service)
    store = contract_bundle / ".roadmap" / "activity.jsonl"
    previous_raw = store.read_text(encoding="utf-8")
    previous_count = len(parse_event_store(contract_bundle))
    expected_sha = hashlib.sha256(previous_raw.encode("utf-8")).hexdigest()

    preview = service.clear_activity(force=True, dry_run=True)
    assert preview["previous_log_sha256"] == expected_sha
    assert store.read_text(encoding="utf-8") == previous_raw

    result = service.clear_activity(force=True)

    first = parse_event_store(contract_bundle)[0]
    cleared = first["payload"]["cleared_log"]
    assert result["previous_log_sha256"] == expected_sha
    assert cleared["previous_log_sha256"] == expected_sha
    assert cleared["previous_event_count"] == previous_count
    backup = contract_bundle / cleared["backup_path"]
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == expected_sha
    assert service.verify()["verify_status"] == "ok"
    assert len(service.list_lessons(status="active")["lessons"]) == 3


@pytest.mark.parametrize("action", ["claim", "complete", "review", "issue.report"])
def test_submit_rejects_orchestrator_actor(contract_bundle: Path, repo_root: Path, action: str) -> None:
    service = _workspace(contract_bundle, repo_root, strict=False)
    _seed(service)
    if action in {"complete", "review", "issue.report"}:
        service.claim_task("T-A", actor="agent-impl")
    if action == "review":
        service.complete_task(
            "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "a\n"}]
        )
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        if action == "claim":
            service.claim_task("T-A", actor="orchestrator")
        elif action == "complete":
            service.complete_task(
                "T-A",
                actor="orchestrator",
                checks=["unit"],
                file_updates=[{"path": "src/a.txt", "content": "a\n"}],
            )
        elif action == "review":
            service.review_task("T-A", actor="orchestrator", decision="approve")
        else:
            service.report_issue(
                "T-A",
                actor="orchestrator",
                issue_id="ISS-X",
                severity="low",
                title="t",
                symptom="s",
                repro_steps=["r"],
            )

    assert exc.value.code == "ORCHESTRATOR_IMPERSONATION"
    assert len(parse_event_store(contract_bundle)) == before
