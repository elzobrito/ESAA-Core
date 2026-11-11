import json

import pytest
import yaml

from esaa.bootstrap import bootstrap_workspace
from esaa.errors import ESAAError
from esaa.service import ESAAService


def test_task_create_limits_replay_and_caps(tmp_path):
    bootstrap_workspace(tmp_path)
    svc = ESAAService(tmp_path)
    svc.init()
    policy_path = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
    p = yaml.safe_load(policy_path.read_text())
    p["resource_limit_caps"] = {
        "max_file_updates": 32,
        "max_bytes_per_update": 4194304,
        "max_bytes_total": 8388608,
    }
    policy_path.write_text(yaml.safe_dump(p))
    svc.create_task("A", task_kind="impl", title="A", resource_limits={"max_bytes_per_update": 4194304})
    assert svc.task_state("A")["task"]["resource_limits"] == {"max_bytes_per_update": 4194304}
    assert svc.dispatch_context("A")["task"]["resource_limits"] == {"max_bytes_per_update": 4194304}
    assert svc.verify()["verify_status"] == "ok"
    with pytest.raises(ESAAError):
        svc.create_task("B", task_kind="impl", title="B", resource_limits={"max_bytes_per_update": 4194305})
    with pytest.raises(ESAAError):
        svc.create_task("C", task_kind="impl", title="C", resource_limits={"max_file_updates": True})


def test_cli_limits_end_to_end(tmp_path):
    import os
    import subprocess
    import sys

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
    p = run("task", "create", "CLI", "--kind", "impl", "--title", "CLI", "--max-file-bytes", "1024")
    assert p.returncode == 0, p.stdout + p.stderr
    s = run("state", "CLI")
    assert json.loads(s.stdout)["task"]["resource_limits"] == {"max_bytes_per_update": 1024}
    invalid = run("task", "create", "NEG", "--kind", "impl", "--title", "bad", "--max-file-bytes", "-1")
    assert invalid.returncode != 0
