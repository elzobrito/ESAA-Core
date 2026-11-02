import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from esaa.bootstrap import bootstrap_workspace
from esaa.contract_migrate import migrate_active_contracts
from esaa.errors import ESAAError
from esaa.service import ESAAService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy_contracts"


def _prepare(tmp_path, caps=True):
    bootstrap_workspace(tmp_path)
    svc = ESAAService(tmp_path)
    svc.init()
    if caps:
        path = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
        policy = yaml.safe_load(path.read_text())
        policy["resource_limit_caps"] = {
            "max_file_updates": 32,
            "max_bytes_per_update": 4194304,
            "max_bytes_total": 8388608,
        }
        path.write_text(yaml.safe_dump(policy))
    return svc


def test_amend_todo_and_set_in_progress_limits(tmp_path):
    svc = _prepare(tmp_path)
    svc.create_task("A", task_kind="impl", title="A")
    svc.amend_task("A", resource_limits={"max_bytes_per_update": 1024})
    assert svc.task_state("A")["task"]["resource_limits"] == {"max_bytes_per_update": 1024}
    svc.claim_task("A", actor="agent-impl")
    with pytest.raises(ESAAError) as amend_exc:
        svc.amend_task("A", resource_limits={"max_bytes_per_update": 2048})
    assert amend_exc.value.code == "INVALID_TRANSITION"
    result = svc.set_task_limits(
        "A",
        {"max_bytes_per_update": 4194304},
        reason="PTB FFV1 exceeds default 2MiB",
        authorized_by="operator",
    )
    assert result["previous"] == {"max_bytes_per_update": 1024}
    task = svc.task_state("A")["task"]
    assert task["resource_limits"] == {"max_bytes_per_update": 4194304}
    assert svc.dispatch_context("A")["task"]["resource_limits"]["max_bytes_per_update"] == 4194304
    assert svc.verify()["verify_status"] == "ok"
    with pytest.raises(ESAAError):
        svc.set_task_limits(
            "A",
            {"max_bytes_per_update": 4194305},
            reason="above cap",
            authorized_by="operator",
        )


def test_set_limits_rejects_done_and_staged_submission(tmp_path):
    svc = _prepare(tmp_path)
    svc.create_task("B", task_kind="impl", title="B")
    svc.claim_task("B", actor="agent-impl")
    staging = tmp_path / ".roadmap/staging"
    staging.mkdir(parents=True)
    (staging / "stage-0000.tmp").write_text("x")
    with pytest.raises(ESAAError) as blocked:
        svc.set_task_limits(
            "B",
            {"max_bytes_per_update": 2048},
            reason="raise",
            authorized_by="operator",
        )
    assert blocked.value.code == "LIMITS_CHANGE_BLOCKED"
    (staging / "stage-0000.tmp").unlink()
    svc.complete_task("B", actor="agent-impl", checks=["one"])
    svc.review_task("B", actor="agent-qa", decision="approve")
    with pytest.raises(ESAAError) as done:
        svc.set_task_limits(
            "B",
            {"max_bytes_per_update": 2048},
            reason="too late",
            authorized_by="operator",
        )
    assert done.value.code == "IMMUTABLE_DONE_VIOLATION"


def test_set_limits_requires_migrated_schema(tmp_path):
    svc = _prepare(tmp_path)
    shutil.copy(FIXTURES / "roadmap.schema.json", tmp_path / ".roadmap/roadmap.schema.json")
    svc.create_task("C", task_kind="impl", title="C")
    svc.claim_task("C", actor="agent-impl")
    with pytest.raises(ESAAError) as exc:
        svc.set_task_limits(
            "C",
            {"max_bytes_per_update": 2048},
            reason="needs schema",
            authorized_by="operator",
        )
    assert exc.value.code == "SCHEMA_INVALID"
    migrate_active_contracts(tmp_path)
    svc.set_task_limits(
        "C",
        {"max_bytes_per_update": 2048},
        reason="after migrate",
        authorized_by="operator",
    )
    assert svc.task_state("C")["task"]["resource_limits"]["max_bytes_per_update"] == 2048


def test_cli_set_limits(tmp_path):
    env = dict(os.environ)
    def run(*args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(tmp_path), *args],
            env=env,
            text=True,
            capture_output=True,
        )
    assert run("bootstrap").returncode == 0
    assert run("init").returncode == 0
    created = run("task", "create", "CLI", "--kind", "impl", "--title", "CLI")
    assert created.returncode == 0, created.stdout + created.stderr
    claimed = run("claim", "CLI", "--actor", "agent-impl")
    assert claimed.returncode == 0, claimed.stdout + claimed.stderr
    limits = run(
        "task",
        "set-limits",
        "CLI",
        "--max-file-bytes",
        "1024",
        "--reason",
        "cli",
        "--authorized-by",
        "operator",
    )
    assert limits.returncode == 0, limits.stdout + limits.stderr
    state = json.loads(run("state", "CLI").stdout)
    assert state["task"]["resource_limits"] == {"max_bytes_per_update": 1024}
