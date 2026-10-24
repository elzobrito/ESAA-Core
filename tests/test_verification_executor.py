import copy
import os

import pytest
from test_verification_config import CONFIG, enabled

from esaa.errors import ESAAError
from esaa.store import parse_event_store
from esaa.verification_candidate import prepare_candidate
from esaa.verification_config import normalize_config
from esaa.verification_executor import execute_check


def ready(root, config=None):
    svc = enabled(root)
    if config:
        svc.verification_enable(config)
    (root / "tetris.py").write_text("old\n")
    svc.create_task(
        "T-C", task_kind="impl", title="candidate", boundary_grant=["tetris.py"], executable_checks=["unit"]
    )
    svc.claim_task("T-C", actor="agent-impl")
    candidate = {
        "activity_event": {
            "action": "complete",
            "task_id": "T-C",
            "prior_status": "in_progress",
            "verification": {"checks": ["real unit"]},
        },
        "file_updates": [{"path": "tetris.py", "content": "fixed\n"}],
    }
    return svc, candidate


def test_snapshot_candidate_and_readonly_dry_run(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    prepared = prepare_candidate(contract_bundle, parse_event_store(contract_bundle), "agent-impl", candidate)
    assert prepared["files"] == {"tetris.py": b"fixed\n"}
    import esaa.verification_executor as executor

    monkeypatch.setattr(executor, "execute_check", lambda *args: pytest.fail("dry run executed"))
    before = {str(p): p.read_bytes() for p in contract_bundle.rglob("*") if p.is_file()}
    assert svc.verification_run("T-C", candidate, "agent-impl", dry_run=True)["would_execute"] is False
    assert before == {str(p): p.read_bytes() for p in contract_bundle.rglob("*") if p.is_file()}
    (contract_bundle / "tetris.py").unlink()
    (contract_bundle / "tetris.py").symlink_to("/etc/passwd")
    with pytest.raises(ESAAError, match="symlink"):
        prepare_candidate(contract_bundle, parse_event_store(contract_bundle), "agent-impl", candidate)


def test_result_digest_and_logs(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    import esaa.verification_executor as executor

    monkeypatch.setattr(
        executor,
        "execute_check",
        lambda c, f: {"id": c["id"], "status": "passed", "stdout": "output", "stderr": "", "exit_code": 0},
    )
    result = svc.verification_run("T-C", candidate, "agent-impl")
    assert svc.verification_result(result["run_id"])["status"] == "passed"
    assert (contract_bundle / "tetris.py").read_text() == "old\n"
    p = contract_bundle / result["results"][0]["logs"]["stdout"]["path"]
    p.write_text("tampered")
    with pytest.raises(ESAAError, match="log"):
        svc.verification_result(result["run_id"])


@pytest.mark.skipif(
    os.environ.get("ESAA_TEST_DOCKER") != "1",
    reason="set ESAA_TEST_DOCKER=1 for real local-image Docker tests",
)
def test_real_docker_isolation_and_candidate(contract_bundle):
    config = copy.deepcopy(CONFIG)
    config["checks"][0]["command"] = [
        "/bin/sh",
        "-c",
        "grep -q fixed tetris.py && test ! -e /var/run/docker.sock && test ! -w /etc && "
        'grep -q "CapEff:.*0000000000000000" /proc/self/status && '
        'test "$(id -u)" = 65534 && test ! -e /home/elzobrito && echo isolated',
    ]
    svc, candidate = ready(contract_bundle, config)
    result = svc.verification_run("T-C", candidate, "agent-impl")
    assert result["status"] == "passed", result
    assert (contract_bundle / "tetris.py").read_text() == "old\n"
    payload = svc.verification_result(result["run_id"])
    assert "isolated" in (contract_bundle / payload["results"][0]["logs"]["stdout"]["path"]).read_text()


@pytest.mark.skipif(os.environ.get("ESAA_TEST_DOCKER") != "1", reason="real Docker checks are opt-in")
@pytest.mark.parametrize(
    "command,status,exit_code",
    [
        (["/bin/sh", "-c", "exit 7"], "failed", 7),
        (["/bin/sh", "-c", "sleep 10"], "timeout", None),
        (["/bin/sh", "-c", "yes x | head -c 10000"], "passed", 0),
    ],
)
def test_real_docker_exit_timeout_logs_and_cleanup(command, status, exit_code):
    import subprocess

    config = copy.deepcopy(CONFIG)
    config["checks"][0].update(command=command, timeout_seconds=1, log_bytes=1024)
    check = normalize_config(config)["checks"][0]
    result = execute_check(check, {"tetris.py": b"fixed\n"})
    assert result["status"] == status, result
    assert result["exit_code"] == exit_code
    assert len(result["stdout"].encode()) <= 1024
    if "yes" in " ".join(command):
        assert result["stdout_truncated"]
    assert (
        subprocess.run(["docker", "inspect", result["container_name"]], capture_output=True).returncode != 0
    )


def test_missing_docker_has_no_fallback(monkeypatch):
    import esaa.verification_executor as executor

    def missing(*args, **kwargs):
        raise FileNotFoundError("docker unavailable")

    monkeypatch.setattr(executor, "_docker", missing)
    result = executor.execute_check(normalize_config(CONFIG)["checks"][0], {})
    assert result["status"] == "unavailable"
    assert "docker unavailable" in result["stderr"]


def test_cancellation_cleans_container(monkeypatch):
    import io
    import subprocess

    import esaa.verification_executor as executor

    calls = []

    def docker(args, timeout=15):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"container", stderr=b"")

    class Process:
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")
        returncode = None
        interrupted = False

        def wait(self, timeout):
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            self.returncode = -9

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(executor, "_docker", docker)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = executor.execute_check(normalize_config(CONFIG)["checks"][0], {})
    assert result["status"] == "cancelled"
    assert any(c[:2] == ["rm", "--force"] for c in calls)
