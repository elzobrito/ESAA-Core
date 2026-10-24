"""Run with an installed candidate's Python outside the source checkout.

Creates only disposable workspaces; final code changes pass through ESAA.
Requires the local Alpine digest from the executable-check integration tests.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> None:
    import esaa
    from esaa.constants import PROTOCOL_VERSION

    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    assert Path(esaa.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), esaa.__file__
    assert PROTOCOL_VERSION == "0.4.2"
    work = Path(tempfile.mkdtemp(prefix="esaa-distribution-smoke-"))
    payloads = Path(tempfile.mkdtemp(prefix="esaa-distribution-payloads-"))
    env = {**os.environ, "ESAA_RUNNER_ID": "codex"}
    env.pop("PYTHONPATH", None)
    started = time.monotonic()

    def cli(*words: str, write: bool = False, error: str | None = None) -> dict:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(work), "--runner", "codex", *words],
            env=env,
            cwd=payloads,
            text=True,
            capture_output=True,
            check=False,
        )
        if error:
            assert proc.returncode == 1, (words, proc.stdout, proc.stderr)
            value = json.loads(proc.stderr)
            assert value["error_code"] == error, value
            return value
        assert proc.returncode == 0, (words, proc.stdout, proc.stderr)
        value = json.loads(proc.stdout)
        if write:
            assert cli("verify")["verify_status"] == "ok"
        return value

    def payload(name: str, value: object) -> Path:
        path = payloads / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    image = "alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
    config = {
        "checks": [
            {
                "id": "unit",
                "image": image,
                "command": ["/bin/sh", "-c", "grep -q fixed tetris.py"],
                "inputs": ["tetris.py"],
            },
            {
                "id": "regression",
                "image": image,
                "command": ["/bin/sh", "-c", "grep -q BOARD=20 tetris.py"],
                "inputs": ["tetris.py"],
            },
        ]
    }
    cli("bootstrap", "--profile", "public")
    cli("init", write=True)
    cli("chain", "init", write=True)
    cli("verification", "enable", "--config", str(payload("config.json", config)), write=True)
    cli(
        "task",
        "create",
        "T-SMOKE",
        "--kind",
        "impl",
        "--title",
        "Synthetic Tetris fixture",
        "--output",
        "tetris.py",
        "--boundary-grant",
        "tetris.py",
        "--executable-check",
        "unit",
        write=True,
    )
    cli("dispatch-context", "T-SMOKE")
    cli("claim", "T-SMOKE", "--actor", "agent-impl", write=True)
    candidate = {
        "activity_event": {
            "action": "complete",
            "task_id": "T-SMOKE",
            "prior_status": "in_progress",
            "verification": {"checks": ["Observed synthetic marker in Docker"]},
        },
        "file_updates": [{"path": "tetris.py", "content": "BOARD=10\n# fixed\n"}],
    }
    cli(
        "submit",
        "--actor",
        "agent-impl",
        "--dry-run",
        str(payload("missing.json", candidate)),
        error="VERIFICATION_REQUIRED",
    )
    result = cli(
        "verification",
        "run",
        "T-SMOKE",
        "--actor",
        "agent-impl",
        "--candidate",
        str(payload("candidate.json", candidate)),
        write=True,
    )
    assert result["status"] == "passed"
    candidate["activity_event"]["verification"]["execution_id"] = result["run_id"]
    stale = copy.deepcopy(candidate)
    stale["file_updates"][0]["content"] = "BOARD=11\n# fixed\n"
    cli(
        "submit",
        "--actor",
        "agent-impl",
        "--dry-run",
        str(payload("stale.json", stale)),
        error="VERIFICATION_STALE",
    )
    cli("submit", "--actor", "agent-impl", "--dry-run", str(payload("candidate.json", candidate)))
    cli(
        "complete",
        "T-SMOKE",
        "--actor",
        "agent-impl",
        "--check",
        "Observed marker",
        "--execution-id",
        result["run_id"],
        "--file-updates",
        str(payload("updates.json", candidate["file_updates"])),
        write=True,
    )
    cli("review", "T-SMOKE", "--actor", "agent-qa", "--decision", "approve", write=True)
    assert (work / "tetris.py").read_text() == "BOARD=10\n# fixed\n"
    cli(
        "issue",
        "report",
        "T-SMOKE",
        "--actor",
        "agent-qa",
        "--issue-id",
        "ISS-SMOKE",
        "--severity",
        "medium",
        "--title",
        "Synthetic regression fixture",
        "--symptom",
        "Fixture must use BOARD=20",
        "--repro-step",
        "Check synthetic board constant",
        write=True,
    )
    cli(
        "hotfix",
        "create",
        "--issue-id",
        "ISS-SMOKE",
        "--fixes",
        "T-SMOKE",
        "--scope-patch",
        "tetris.py",
        "--boundary-grant",
        "tetris.py",
        "--output",
        "tetris.py",
        "--executable-check",
        "unit",
        "--executable-check",
        "regression",
        write=True,
    )
    hotfix_id = "HF-ISS-SMOKE"
    cli("claim", hotfix_id, "--actor", "agent-impl", write=True)
    before = (work / "tetris.py").read_bytes()
    hotfix = {
        "activity_event": {
            "action": "complete",
            "task_id": hotfix_id,
            "prior_status": "in_progress",
            "issue_id": "ISS-SMOKE",
            "fixes": "T-SMOKE",
            "verification": {"checks": ["Unit marker observed", "Regression BOARD=20 observed"]},
        },
        "file_updates": [
            {
                "path": "tetris.py",
                "base_sha256": hashlib.sha256(before).hexdigest(),
                "edits": [{"old_string": "BOARD=10", "new_string": "BOARD=20"}],
            }
        ],
    }
    hf_result = cli(
        "verification",
        "run",
        hotfix_id,
        "--actor",
        "agent-impl",
        "--candidate",
        str(payload("hotfix.json", hotfix)),
        write=True,
    )
    assert hf_result["status"] == "passed" and len(hf_result["results"]) == 2
    hotfix["activity_event"]["verification"]["execution_id"] = hf_result["run_id"]
    cli("submit", "--actor", "agent-impl", str(payload("hotfix.json", hotfix)), write=True)
    cli("review", hotfix_id, "--actor", "agent-qa", "--decision", "approve", write=True)
    assert cli("state", "T-SMOKE")["task"]["status"] == "done"
    assert cli("state", hotfix_id)["task"]["status"] == "done"
    assert (work / "tetris.py").read_text() == "BOARD=20\n# fixed\n"
    assert json.loads((work / ".roadmap/issues.json").read_text())["issues"][0]["status"] == "resolved"
    snapshot = {
        str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in work.rglob("*")
        if p.is_file()
    }
    first = cli("task", "list", "--status", "done", "--limit", "1")
    second = cli("task", "list", "--status", "done", "--limit", "1", "--cursor", first["next_cursor"])
    assert first["tasks"][0]["task_id"] != second["tasks"][0]["task_id"]
    events = cli("activity", "list", "--hide-verify")
    assert all(not event["action"].startswith("verify.") for event in events["events"])
    assert cli("verification", "result", hf_result["run_id"])["status"] == "passed"
    assert snapshot == {
        str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in work.rglob("*")
        if p.is_file()
    }
    cli(
        "runner",
        "metrics",
        "--task-id",
        hotfix_id,
        "--actor",
        "agent-impl",
        "--runner-id",
        "codex",
        "--runner-kind",
        "integration-test",
        "--command-surface",
        "cli",
        "--status",
        "success",
        "--latency-ms",
        str(round((time.monotonic() - started) * 1000)),
        write=True,
    )
    metrics = cli("metrics")
    assert metrics["runner"]["events"] == 1 and metrics["attempts_total"] == 0
    verify = cli("verify")
    chain = cli("verify", "--chain")
    assert chain["chain_status"] == "ok"
    summary = {
        "label": args.label,
        "workspace": str(work),
        "python": sys.executable,
        "package": esaa.__file__,
        "version": importlib.metadata.version("esaa-core"),
        "cryptography": importlib.metadata.version("cryptography"),
        "protocol": PROTOCOL_VERSION,
        "tasks_done": ["T-SMOKE", hotfix_id],
        "issue_resolved": True,
        "negative_controls": ["VERIFICATION_REQUIRED", "VERIFICATION_STALE"],
        "executed_checks": len(result["results"]) + len(hf_result["results"]),
        "queries_read_only": True,
        "verify": verify,
        "chain": chain,
        "boundary": "Synthetic fixture only; no original Tetris or GUI was executed.",
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
