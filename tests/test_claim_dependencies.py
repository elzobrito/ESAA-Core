"""AUD-O0-010 (GOV-02) - claim so e admitido com dependencias done e sem superseded_by.

A regra vale na admissao (submit); o replay de claims historicos nao muda.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from esaa import cli
from esaa.claim_admission import assert_claim_admissible
from esaa.errors import ESAAError
from esaa.events import make_event
from esaa.reject_codes import ALL_CODES, DEPENDENCY_NOT_DONE, TASK_SUPERSEDED, WORKFLOW_GATE_CODES
from esaa.service import ESAAService
from esaa.store import append_events, next_event_seq, parse_event_store


def _service(root: Path) -> ESAAService:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.create_task("T-B", "impl", "depende de A", outputs=["src/b.txt"], depends_on=["T-A"])
    return service


def _finish(service: ESAAService, task_id: str, path: str) -> None:
    service.claim_task(task_id, actor="agent-impl")
    service.complete_task(
        task_id,
        actor="agent-impl",
        checks=["unit"],
        file_updates=[{"path": path, "content": "x\n"}],
    )
    service.review_task(task_id, actor="agent-impl", decision="approve")


def _status(service: ESAAService, task_id: str) -> str:
    return service.task_state(task_id)["task"]["status"]


def test_codes_are_registered_workflow_gates() -> None:
    assert {DEPENDENCY_NOT_DONE, TASK_SUPERSEDED} <= WORKFLOW_GATE_CODES <= ALL_CODES


def test_claim_rejected_while_dependency_is_todo(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        service.claim_task("T-B", actor="agent-impl")

    assert exc.value.code == DEPENDENCY_NOT_DONE
    assert "T-A=todo" in exc.value.message
    assert exc.value.penalizes_counter is False
    assert len(parse_event_store(contract_bundle)) == before
    assert _status(service, "T-B") == "todo"


@pytest.mark.parametrize("dep_status", ["in_progress", "review"])
def test_claim_rejected_until_dependency_is_done(contract_bundle: Path, dep_status: str) -> None:
    service = _service(contract_bundle)
    service.claim_task("T-A", actor="agent-impl")
    if dep_status == "review":
        service.complete_task(
            "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "a\n"}]
        )
    assert _status(service, "T-A") == dep_status

    with pytest.raises(ESAAError) as exc:
        service.claim_task("T-B", actor="agent-impl")

    assert exc.value.code == DEPENDENCY_NOT_DONE
    assert f"T-A={dep_status}" in exc.value.message


def test_claim_accepted_after_dependency_done(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    _finish(service, "T-A", "src/a.txt")

    result = service.claim_task("T-B", actor="agent-impl")

    assert result["status"] == "accepted"
    assert _status(service, "T-B") == "in_progress"
    assert service.verify()["verify_status"] == "ok"


def test_dry_run_claim_is_also_rejected(contract_bundle: Path) -> None:
    service = _service(contract_bundle)

    with pytest.raises(ESAAError) as exc:
        service.claim_task("T-B", actor="agent-impl", dry_run=True)

    assert exc.value.code == DEPENDENCY_NOT_DONE


def test_unknown_dependency_counts_as_pending() -> None:
    task = {"task_id": "T-X", "status": "todo", "depends_on": ["T-MISSING"]}

    with pytest.raises(ESAAError) as exc:
        assert_claim_admissible([task], task)

    assert exc.value.code == DEPENDENCY_NOT_DONE
    assert "T-MISSING=unknown" in exc.value.message


def test_claim_of_superseded_task_is_rejected(contract_bundle: Path, repo_root: Path) -> None:
    # supersedes e campo G07: usa o schema de projecao distribuido no pacote.
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "roadmap.schema.json",
        contract_bundle / ".roadmap" / "roadmap.schema.json",
    )
    service = _service(contract_bundle)
    service.create_task("T-A2", "impl", "substitui A", outputs=["src/a2.txt"], supersedes=["T-A"])

    with pytest.raises(ESAAError) as exc:
        service.claim_task("T-A", actor="agent-impl")

    assert exc.value.code == TASK_SUPERSEDED
    assert "T-A2" in exc.value.message
    assert service.claim_task("T-A2", actor="agent-impl")["status"] == "accepted"


def test_prior_status_mismatch_still_wins_for_non_todo_task(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    service.claim_task("T-A", actor="agent-impl")

    with pytest.raises(ESAAError) as exc:
        service.claim_task("T-A", actor="agent-other")

    assert exc.value.code == "PRIOR_STATUS_MISMATCH"


def test_historical_premature_claim_still_replays(contract_bundle: Path) -> None:
    """Claims aceitos por runtimes anteriores continuam validos no replay."""
    service = _service(contract_bundle)
    events = parse_event_store(contract_bundle)
    legacy_claim = make_event(
        next_event_seq(events),
        actor="agent-impl",
        action="claim",
        payload={"action": "claim", "task_id": "T-B", "prior_status": "todo"},
    )
    append_events(contract_bundle, [legacy_claim])

    service.project()

    assert service.verify()["verify_status"] == "ok"
    assert _status(service, "T-B") == "in_progress"
    assert _status(service, "T-A") == "todo"


def test_cli_exit_code_and_error_payload(contract_bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _service(contract_bundle)
    capsys.readouterr()

    rc = cli.main(["--root", str(contract_bundle), "claim", "T-B", "--actor", "agent-impl"])

    assert rc == 1
    assert '"error_code": "DEPENDENCY_NOT_DONE"' in capsys.readouterr().err
