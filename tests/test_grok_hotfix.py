import pytest

from esaa.errors import ESAAError
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store


def ready(root):
    (root / ".roadmap/RUNTIME_POLICY.yaml").write_text("review_authorization: qa_role\n")
    svc = ESAAService(root)
    svc.init(with_demo_tasks=True)
    svc.claim_task("T-1010", actor="agent-impl")
    svc.complete_task("T-1010", actor="agent-impl", checks=["done"])
    svc.review_task("T-1010", actor="agent-qa", decision="approve")
    svc.report_issue(
        "T-1010",
        actor="agent-qa",
        issue_id="ISS-G",
        severity="high",
        title="defect",
        symptom="root file",
        repro_steps=["inspect"],
    )
    return svc


def test_root_hotfix_grant_and_replay(contract_bundle):
    svc = ready(contract_bundle)
    svc.create_hotfix(
        "ISS-G", "T-1010", scope_patch=["tetris.py"], boundary_grant=["tetris.py"], outputs=["tetris.py"]
    )
    task = svc.task_state("HF-ISS-G")["task"]
    assert task["outputs"]["files"] == ["tetris.py"]
    svc.claim_task("HF-ISS-G", actor="agent-impl")
    svc.complete_task(
        "HF-ISS-G",
        actor="agent-impl",
        checks=["unit", "regression"],
        file_updates=[{"path": "tetris.py", "content": "fixed\n"}],
    )
    svc.review_task("HF-ISS-G", actor="agent-qa", decision="approve")
    assert svc.task_state("T-1010")["task"]["status"] == "done"
    assert svc.verify()["verify_status"] == "ok"
    assert (contract_bundle / "tetris.py").read_text() == "fixed\n"
    assert svc.task_state("HF-ISS-G")["task"]["boundary_grant"] == ["tetris.py"]


def test_missing_grant_and_amend_todo(contract_bundle):
    svc = ready(contract_bundle)
    svc.create_hotfix("ISS-G", "T-1010")
    svc.amend_task("HF-ISS-G", scope_patch=["tetris.py"], outputs=["tetris.py"])
    svc.amend_task("HF-ISS-G", boundary_grant=["tetris.py"])
    svc.amend_task("HF-ISS-G", clear_boundary_grants=True)
    svc.claim_task("HF-ISS-G", actor="agent-impl")
    with pytest.raises(ESAAError, match="not allowed"):
        svc.complete_task(
            "HF-ISS-G",
            actor="agent-impl",
            checks=["a", "b"],
            file_updates=[{"path": "tetris.py", "content": "fixed"}],
        )
    with pytest.raises(ESAAError, match="todo"):
        svc.amend_task("HF-ISS-G", boundary_grant=["tetris.py"])


@pytest.mark.parametrize("path", ["/tmp/x.py", "../x.py", ".roadmap/evil.json", "C:/x.py"])
def test_unsafe_hotfix_scope(contract_bundle, path):
    svc = ready(contract_bundle)
    with pytest.raises(ESAAError):
        svc.create_hotfix("ISS-G", "T-1010", scope_patch=[path])


def test_duplicate_has_recovery_and_forbidden_grant(contract_bundle):
    svc = ready(contract_bundle)
    with pytest.raises(ESAAError):
        svc.create_hotfix("ISS-G", "T-1010", boundary_grant=[".roadmap/**"])
    svc.create_hotfix("ISS-G", "T-1010")
    with pytest.raises(ESAAError, match="task amend"):
        svc.create_hotfix("ISS-G", "T-1010")
    svc.amend_task("HF-ISS-G", boundary_grant=["tetris.py"])
    events = parse_event_store(contract_bundle)
    next(e for e in events if e["action"] == "task.amend")["payload"]["boundary_grant"] = ["../unsafe"]
    with pytest.raises(ESAAError):
        materialize(events)


def test_cli_forwards_grants_outputs(contract_bundle, capsys):
    from esaa.cli import main

    svc = ready(contract_bundle)
    assert (
        main(
            [
                "--root",
                str(contract_bundle),
                "hotfix",
                "create",
                "--issue-id",
                "ISS-G",
                "--fixes",
                "T-1010",
                "--scope-patch",
                "tetris.py",
                "--boundary-grant",
                "tetris.py",
                "--output",
                "tetris.py",
            ]
        )
        == 0
    )
    task = svc.task_state("HF-ISS-G")["task"]
    assert task["boundary_grant"] == ["tetris.py"]
    assert task["outputs"]["files"] == ["tetris.py"]


def test_legacy_runtime_scope_remains_replayable(contract_bundle):
    svc = ready(contract_bundle)
    svc.create_hotfix("ISS-G", "T-1010", scope_patch=["runtime://catalog/item.py"])
    assert svc.task_state("HF-ISS-G")["task"]["scope_patch"] == ["runtime://catalog/item.py"]
    assert svc.verify()["verify_status"] == "ok"


@pytest.mark.parametrize(
    "scope", ["runtime:///absolute.py", "runtime://catalog/../item.py", "runtime://../item.py"]
)
def test_runtime_scope_rejects_unsafe_forms(contract_bundle, scope):
    svc = ready(contract_bundle)
    with pytest.raises(ESAAError):
        svc.create_hotfix("ISS-G", "T-1010", scope_patch=[scope])


def test_legacy_positional_dry_run_apis_remain_non_mutating(contract_bundle):
    svc = ready(contract_bundle)
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
    preview = svc.create_task(
        "T-OLD", "impl", "legacy", None, None, None, None, None, None, None, None, None, True
    )
    assert preview["status"] == "dry_run"
    preview = svc.create_hotfix("ISS-G", "T-1010", None, True)
    assert preview["status"] == "dry_run"
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    svc.create_hotfix("ISS-G", "T-1010")
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
    preview = svc.amend_task("HF-ISS-G", None, "new title", None, None, None, None, None, None, None, True)
    assert preview["status"] == "dry_run"
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    assert svc.task_state("HF-ISS-G")["task"]["title"] != "new title"
