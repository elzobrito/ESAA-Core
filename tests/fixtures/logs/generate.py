"""Generate authentic release fixtures in disposable, isolated environments."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

PYPI_URL = "https://pypi.org/pypi/esaa-core/json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def produce(workspace: Path, output: Path) -> None:
    """This function runs only inside the historical release's isolated venv."""
    import esaa
    from esaa.bootstrap import bootstrap_workspace
    from esaa.projector import materialize
    from esaa.service import ESAAService
    from esaa.store import parse_event_store

    module_path = Path(esaa.__file__).resolve()
    if not module_path.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"historical import escaped venv: {module_path}")
    service = ESAAService(workspace)
    calls = [
        {
            "method": "bootstrap_workspace",
            "kwargs": {"profile": "public"},
            "result": bootstrap_workspace(workspace, profile="public"),
        }
    ]

    def call(method: str, **kwargs: Any) -> Any:
        function = getattr(service, method)
        inspect.signature(function).bind(**kwargs)
        result = function(**kwargs)
        calls.append({"method": f"ESAAService.{method}", "kwargs": kwargs, "result": result})
        return result

    call("init", run_id="RUN-HISTORICAL", master_correlation_id="CID-HISTORICAL")
    call(
        "create_task",
        task_id="HISTORY-001",
        task_kind="impl",
        title="Historical fixture task",
        description="Exercise the published event workflow without modifying its log",
        outputs=["src/history.txt"],
    )
    call("claim_task", task_id="HISTORY-001", actor="agent-impl")
    call(
        "complete_task",
        task_id="HISTORY-001",
        actor="agent-impl",
        checks=["Historical workflow check", "Historical projection check"],
    )
    call("review_task", task_id="HISTORY-001", actor="agent-qa", decision="approve")
    call(
        "report_issue",
        task_id="HISTORY-001",
        actor="agent-impl",
        issue_id="ISS-HISTORY-001",
        severity="medium",
        title="Historical fixture issue",
        symptom="Fixture issue for the published hotfix workflow",
        repro_steps=["Replay the completed historical fixture task"],
    )
    call(
        "create_hotfix",
        issue_id="ISS-HISTORY-001",
        fixes="HISTORY-001",
        scope_patch=["src/history.txt"],
    )
    verification = call("verify")
    events = parse_event_store(workspace)
    roadmap, _, _ = materialize(events)
    if verification["verify_status"] != "ok":
        raise RuntimeError(f"producer verification failed: {verification}")
    output.mkdir(parents=True, exist_ok=True)
    log = (workspace / ".roadmap/activity.jsonl").read_bytes()
    (output / "activity.jsonl").write_bytes(log)
    write_json(
        output / "producer.json",
        {
            "producer_version": importlib.metadata.version("esaa-core"),
            "runtime_module_path": str(module_path),
            "python_version": sys.version,
            "log_sha256": sha256(log),
            "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
            "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
            "api_calls": calls,
        },
    )


def generate(args: argparse.Namespace) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(
        {
            "ESAA_RUNNER_ID": "codex",
            "ESAA_RUNNER_KIND": "agent",
            "ESAA_COMMAND_SURFACE": "python-api",
            "ESAA_TRANSITION_MESSAGES": "0",
            "ESAA_COMPLETION_ALARM": "0",
        }
    )
    if args.metadata:
        metadata_bytes = args.metadata.read_bytes()
    else:
        with urllib.request.urlopen(PYPI_URL) as response:
            metadata_bytes = response.read()
    metadata = json.loads(metadata_bytes)
    releases = {
        version: files
        for version, files in metadata["releases"].items()
        if version.startswith("0.5.0b") and files
    }
    if args.versions:
        releases = {version: releases[version] for version in args.versions}
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="esaa-historical-") as temporary:
        temporary_root = Path(temporary)
        for version in sorted(releases, key=lambda value: int(value.split("b")[-1])):
            wheels = [file for file in releases[version] if file["packagetype"] == "bdist_wheel"]
            if len(wheels) != 1:
                raise RuntimeError(f"expected one official wheel for {version}: {wheels}")
            wheel = wheels[0]
            wheel_path = temporary_root / wheel["filename"]
            cached = args.wheel_cache / wheel["filename"] if args.wheel_cache else None
            if cached and cached.exists():
                data = cached.read_bytes()
            else:
                with urllib.request.urlopen(wheel["url"]) as response:
                    data = response.read()
            if sha256(data) != wheel["digests"]["sha256"]:
                raise RuntimeError(f"official wheel SHA256 mismatch: {version}")
            wheel_path.write_bytes(data)
            version_root = temporary_root / version
            venv = version_root / "venv"
            subprocess.run([args.python, "-m", "venv", str(venv)], env=env, check=True)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            install = [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel_path),
            ]
            installed = subprocess.run(install, env=env, check=True, text=True, capture_output=True)
            destination = args.output / version
            subprocess.run(
                [
                    str(python),
                    "-B",
                    str(Path(__file__).resolve()),
                    "--produce",
                    str(version_root / "workspace"),
                    str(destination),
                ],
                cwd=temporary_root,
                env=env,
                check=True,
            )
            producer_path = destination / "producer.json"
            producer = json.loads(producer_path.read_text(encoding="utf-8"))
            producer.update(
                {
                    "wheel_sha256": wheel["digests"]["sha256"],
                    "wheel_url": wheel["url"],
                    "wheel_filename": wheel["filename"],
                    "metadata_url": PYPI_URL,
                    "metadata_sha256": sha256(metadata_bytes),
                    "install_command": install,
                    "install_stdout": installed.stdout,
                    "hash_domain": "ESAA roadmap: schema_version, project, tasks, indexes",
                }
            )
            write_json(destination / "expected.json", producer)
            producer_path.unlink()
            print(
                f"{version}: {producer['last_event_seq']} events {producer['projection_hash_sha256']}",
                flush=True,
            )
            shutil.rmtree(version_root)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--produce":
        produce(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel-cache", type=Path)
    parser.add_argument("--metadata", type=Path, help="use a pinned official PyPI metadata snapshot")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--versions", nargs="+")
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
