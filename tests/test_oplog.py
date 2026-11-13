from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from esaa.cli import main

EXPECTED_FIELDS = {
    "ts",
    "esaa_version",
    "pid",
    "command",
    "runner",
    "root",
    "duration_ms",
    "lock_wait_ms",
    "lock_retries",
    "lock_takeovers",
    "events_appended",
    "exit_code",
    "error_code",
    "dry_run",
}


def _run_cli_subprocess(args: list[str], *, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_extra)
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src_dir
    return subprocess.run(
        [sys.executable, "-m", "esaa", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _parallel_verify_worker(workspace: str, log_file: str, idx: int) -> int:
    proc = _run_cli_subprocess(
        ["--root", workspace, "--runner", f"worker-{idx}", "verify"],
        env_extra={"ESAA_LOG": log_file},
    )
    return proc.returncode


def test_oplog_not_created_when_env_unset_or_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.delenv("ESAA_LOG", raising=False)
    assert main(["--root", str(ws), "init"]) == 0
    assert not (tmp_path / "oplog.jsonl").exists()

    monkeypatch.setenv("ESAA_LOG", "   ")
    assert main(["--root", str(ws), "verify"]) == 0
    assert list(tmp_path.iterdir()) == [ws]


def test_oplog_success_dry_run_and_no_content_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    log_file = tmp_path / "logs" / "esaa.jsonl"
    monkeypatch.setenv("ESAA_LOG", str(log_file))
    monkeypatch.setenv("SECRET_ENV_MARKER", "DO_NOT_LOG_THIS_SECRET")

    assert main(["--root", str(ws), "bootstrap"]) == 0
    assert main(["--root", str(ws), "--runner", "codex", "init"]) == 0
    assert (
        main(
            [
                "--root",
                str(ws),
                "task",
                "create",
                "T-001",
                "--kind",
                "impl",
                "--title",
                "Title",
                "--description",
                "SECRET_DESCRIPTION_TEXT",
                "--output",
                "src/x.py",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--root",
                str(ws),
                "--runner",
                "codex",
                "claim",
                "T-001",
                "--actor",
                "agent-impl",
                "--notes",
                "SECRET_CLAIM_NOTES",
                "--dry-run",
            ]
        )
        == 0
    )

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    records = [json.loads(line) for line in lines]
    for rec in records:
        assert set(rec.keys()) == EXPECTED_FIELDS

    assert records[0]["command"] == "bootstrap"
    assert records[1]["command"] == "init"
    assert records[1]["runner"] == "codex"
    assert records[1]["exit_code"] == 0
    assert records[1]["error_code"] is None
    assert records[1]["events_appended"] >= 1
    assert records[1]["dry_run"] is False

    assert records[2]["command"] == "task create"
    assert records[3]["command"] == "claim"
    assert records[3]["dry_run"] is True
    assert records[3]["events_appended"] == 0

    raw_text = log_file.read_text(encoding="utf-8")
    assert "SECRET_DESCRIPTION_TEXT" not in raw_text
    assert "SECRET_CLAIM_NOTES" not in raw_text
    assert "DO_NOT_LOG_THIS_SECRET" not in raw_text


def test_oplog_domain_error_and_verify_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    log_file = tmp_path / "esaa.jsonl"
    monkeypatch.setenv("ESAA_LOG", str(log_file))

    assert main(["--root", str(ws), "bootstrap"]) == 0
    assert main(["--root", str(ws), "init"]) == 0
    # Domain error: claim unknown task -> exit 1
    assert main(["--root", str(ws), "claim", "NO-SUCH-TASK", "--actor", "agent-impl"]) == 1

    # Corrupt roadmap projection to trigger verify mismatch -> exit 2
    roadmap_path = ws / ".roadmap" / "roadmap.json"
    roadmap_data = json.loads(roadmap_path.read_text(encoding="utf-8"))
    roadmap_data["meta"]["run"]["projection_hash_sha256"] = "0" * 64
    roadmap_path.write_text(json.dumps(roadmap_data), encoding="utf-8")
    assert main(["--root", str(ws), "verify"]) == 2

    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 4
    assert records[2]["exit_code"] == 1
    assert records[2]["error_code"] == "TASK_NOT_FOUND"
    assert records[3]["exit_code"] == 2
    assert records[3]["error_code"] == "mismatch"


def test_oplog_argparse_error_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_file = tmp_path / "esaa.jsonl"
    monkeypatch.setenv("ESAA_LOG", str(log_file))
    with pytest.raises(SystemExit) as exc_info:
        main(["--root", str(tmp_path), "nonexistent-subcommand"])
    assert exc_info.value.code == 2

    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["exit_code"] == 2
    assert records[0]["error_code"] == "INVALID_ARGUMENT"


def test_oplog_unwritable_path_is_silent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    assert main(["--root", str(ws), "init"]) == 0

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file", encoding="utf-8")
    bad_log = blocker / "esaa.jsonl"

    baseline = _run_cli_subprocess(["--root", str(ws), "verify"], env_extra={"ESAA_LOG": ""})
    with_bad_log = _run_cli_subprocess(["--root", str(ws), "verify"], env_extra={"ESAA_LOG": str(bad_log)})
    assert with_bad_log.returncode == baseline.returncode == 0
    assert with_bad_log.stdout == baseline.stdout
    assert with_bad_log.stderr == baseline.stderr


def test_oplog_eight_parallel_processes_produce_valid_lines(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    assert main(["--root", str(ws), "init"]) == 0
    log_file = tmp_path / "parallel.jsonl"

    with ProcessPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(_parallel_verify_worker, [str(ws)] * 8, [str(log_file)] * 8, range(8)))

    assert all(code == 0 for code in codes)
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 8
    parsed = [json.loads(line) for line in lines]
    assert all(set(item.keys()) == EXPECTED_FIELDS for item in parsed)
    assert all(item["command"] == "verify" and item["exit_code"] == 0 for item in parsed)
