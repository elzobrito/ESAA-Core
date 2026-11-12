import hashlib
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="binary staging requires secure POSIX dirfd support"
)


def test_binary_input_command(tmp_path):
    def run(*args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(tmp_path), *args],
            text=True,
            capture_output=True,
            env=dict(os.environ),
        )

    for args in [
        ("bootstrap",),
        ("init",),
        ("task", "create", "A", "--kind", "impl", "--title", "A", "--max-file-bytes", "1024"),
        ("claim", "A", "--actor", "agent-impl"),
    ]:
        p = run(*args)
        assert p.returncode == 0, p.stdout + p.stderr
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    data = b"\x89PNG\r\n" + b"payload"
    (src / "test.png").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    data_size = len(data)

    def stage(actor="agent-impl", source="src/test.png", size=data_size, digest=sha):
        return run("input", "binary", "A", source, "--actor", actor, "--size", str(size), "--sha256", digest)

    for p in [stage(actor="agent-spec"), stage(source="../secret"), stage(size=2000), stage(digest="0" * 64)]:
        assert p.returncode != 0
    p = stage()
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads(p.stdout)
    assert result["binary"]["source"] == sha
    key = hashlib.sha256(b"A").hexdigest()
    assert (tmp_path / ".roadmap/binary-input" / key / sha).read_bytes() == data
    assert stage().returncode == 0
    assert json.loads(run("verify").stdout)["verify_status"] == "ok"


def test_large_binary_input_under_explicit_task_ceiling(tmp_path):
    import yaml

    def run(*args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(tmp_path), *args],
            text=True,
            capture_output=True,
            env=dict(os.environ),
        )

    assert run("bootstrap").returncode == 0
    assert run("init").returncode == 0
    policy = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
    d = yaml.safe_load(policy.read_text())
    d["resource_limit_caps"] = {
        "max_file_updates": 32,
        "max_bytes_per_update": 4194304,
        "max_bytes_total": 8388608,
    }
    policy.write_text(yaml.safe_dump(d))
    p = run("task", "create", "VID", "--kind", "impl", "--title", "video", "--max-file-bytes", "4194304")
    assert p.returncode == 0, p.stderr
    assert run("claim", "VID", "--actor", "agent-impl").returncode == 0
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    data = bytes(range(256)) * 8500
    (src / "sample.bin").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    p = run(
        "input",
        "binary",
        "VID",
        "src/sample.bin",
        "--actor",
        "agent-impl",
        "--size",
        str(len(data)),
        "--sha256",
        sha,
    )
    assert p.returncode == 0, p.stderr
    staged = tmp_path / ".roadmap/binary-input" / hashlib.sha256(b"VID").hexdigest() / sha
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == sha
