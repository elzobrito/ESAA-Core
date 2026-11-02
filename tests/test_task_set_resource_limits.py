import json
import os
import subprocess
import sys

import yaml


def _run(root, *args):
    return subprocess.run(
        [sys.executable, "-B", "-m", "esaa", "--root", str(root), *args],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def _boot(tmp_path):
    assert _run(tmp_path, "bootstrap").returncode == 0
    assert _run(tmp_path, "init").returncode == 0
    policy = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
    data = yaml.safe_load(policy.read_text())
    data["resource_limit_caps"] = {
        "max_file_updates": 64,
        "max_bytes_per_update": 4194304,
        "max_bytes_total": 8388608,
    }
    policy.write_text(yaml.safe_dump(data))


def test_amend_todo_and_set_limits_on_in_progress(tmp_path):
    _boot(tmp_path)
    created = _run(tmp_path, "task", "create", "A", "--kind", "impl", "--title", "A")
    assert created.returncode == 0, created.stderr
    amended = _run(tmp_path, "task", "amend", "A", "--max-file-bytes", "1024")
    assert amended.returncode == 0, amended.stderr
    assert json.loads(_run(tmp_path, "state", "A").stdout)["task"]["resource_limits"] == {
        "max_bytes_per_update": 1024
    }
    assert _run(tmp_path, "claim", "A", "--actor", "agent-impl").returncode == 0
    todo_style = _run(tmp_path, "task", "amend", "A", "--max-file-bytes", "2048")
    assert todo_style.returncode != 0
    updated = _run(
        tmp_path,
        "task",
        "set-limits",
        "A",
        "--reason",
        "raise ceiling for binary fixture",
        "--authorized-by",
        "operator",
        "--max-file-bytes",
        "4194304",
        "--max-file-updates",
        "40",
    )
    assert updated.returncode == 0, updated.stderr
    limits = json.loads(_run(tmp_path, "state", "A").stdout)["task"]["resource_limits"]
    assert limits == {"max_bytes_per_update": 4194304, "max_file_updates": 40}
    assert json.loads(_run(tmp_path, "verify").stdout)["verify_status"] == "ok"


def test_set_limits_rejects_done_ceiling_and_empty_reason(tmp_path):
    _boot(tmp_path)
    assert _run(tmp_path, "task", "create", "A", "--kind", "impl", "--title", "A").returncode == 0
    assert _run(tmp_path, "claim", "A", "--actor", "agent-impl").returncode == 0
    empty = _run(
        tmp_path,
        "task",
        "set-limits",
        "A",
        "--reason",
        "   ",
        "--authorized-by",
        "operator",
        "--max-file-bytes",
        "1024",
    )
    assert empty.returncode != 0
    over = _run(
        tmp_path,
        "task",
        "set-limits",
        "A",
        "--reason",
        "too large",
        "--authorized-by",
        "operator",
        "--max-file-bytes",
        "4194305",
    )
    assert over.returncode != 0
    assert "RESOURCE_LIMIT_INVALID" in over.stderr + over.stdout
    complete = _run(tmp_path, "complete", "A", "--actor", "agent-impl", "--check", "one", "--check", "two")
    assert complete.returncode == 0, complete.stderr
    review = _run(tmp_path, "review", "A", "--actor", "agent-qa", "--decision", "approve")
    assert review.returncode == 0, review.stderr
    done = _run(
        tmp_path,
        "task",
        "set-limits",
        "A",
        "--reason",
        "after done",
        "--authorized-by",
        "operator",
        "--max-file-bytes",
        "1024",
    )
    assert done.returncode != 0
    assert "IMMUTABLE_DONE_VIOLATION" in done.stderr + done.stdout
