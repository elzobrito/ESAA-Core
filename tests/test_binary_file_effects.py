import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def test_legacy_schema_migrate_then_binary_complete(tmp_path):
    fixtures = Path(__file__).resolve().parent / "fixtures" / "legacy_contracts"

    def run(*args):
        p = subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(tmp_path), *args],
            capture_output=True,
            text=True,
            env=dict(os.environ),
        )
        assert p.returncode == 0, p.stdout + p.stderr
        return json.loads(p.stdout)

    run("bootstrap")
    run("init")
    shutil.copy(fixtures / "agent_result.schema.json", tmp_path / ".roadmap/agent_result.schema.json")
    shutil.copy(fixtures / "roadmap.schema.json", tmp_path / ".roadmap/roadmap.schema.json")
    policy = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
    d = yaml.safe_load(policy.read_text())
    d["resource_limit_caps"] = {
        "max_file_updates": 32,
        "max_bytes_per_update": 4194304,
        "max_bytes_total": 8388608,
    }
    policy.write_text(yaml.safe_dump(d))
    create = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "esaa",
            "--root",
            str(tmp_path),
            "task",
            "create",
            "T",
            "--kind",
            "impl",
            "--title",
            "test",
            "--output",
            "src/video.bin",
            "--max-file-bytes",
            "4194304",
        ],
        capture_output=True,
        text=True,
    )
    assert create.returncode != 0
    run("contract", "migrate")
    run(
        "task",
        "create",
        "T",
        "--kind",
        "impl",
        "--title",
        "test",
        "--output",
        "src/video.bin",
        "--max-file-bytes",
        "4194304",
    )
    run("claim", "T", "--actor", "agent-impl")
    raw = os.urandom(2 * 1024 * 1024 + 100)
    sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / "fixture.bin").write_bytes(raw)
    staged = run(
        "input",
        "binary",
        "T",
        "fixture.bin",
        "--actor",
        "agent-impl",
        "--size",
        str(len(raw)),
        "--sha256",
        sha,
    )
    update = tmp_path / "updates.json"
    update.write_text(json.dumps([{"path": "src/video.bin", "binary": staged["binary"]}]))
    run(
        "complete",
        "T",
        "--actor",
        "agent-impl",
        "--check",
        "one",
        "--check",
        "two",
        "--file-updates",
        str(update),
    )
    dest = tmp_path / "src/video.bin"
    assert dest.read_bytes() == raw
    dest.unlink()
    result = run("effects", "recover")
    assert not result["errors"]
    assert dest.read_bytes() == raw


def test_mkv_full_flow(tmp_path):
    def run(*args):
        p = subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(tmp_path), *args],
            capture_output=True,
            text=True,
            env=dict(os.environ),
        )
        assert p.returncode == 0, p.stdout + p.stderr
        return json.loads(p.stdout)

    run("bootstrap")
    run("init")
    policy = tmp_path / ".roadmap/RUNTIME_POLICY.yaml"
    d = yaml.safe_load(policy.read_text())
    d["resource_limit_caps"] = {
        "max_file_updates": 32,
        "max_bytes_per_update": 4194304,
        "max_bytes_total": 8388608,
    }
    policy.write_text(yaml.safe_dump(d))
    run(
        "task",
        "create",
        "T",
        "--kind",
        "impl",
        "--title",
        "test",
        "--output",
        "src/video.mkv",
        "--max-file-bytes",
        "4194304",
    )
    run("claim", "T", "--actor", "agent-impl")
    import pytest

    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is required to generate an FFV1 fixture")
    source = tmp_path / "fixture.mkv"
    generated = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=960x540:rate=30",
            "-vf",
            "noise=alls=90:allf=t",
            "-frames:v",
            "3",
            "-c:v",
            "ffv1",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr
    raw = source.read_bytes()
    assert len(raw) > 2 * 1024 * 1024
    sha = hashlib.sha256(raw).hexdigest()
    staged = run(
        "input",
        "binary",
        "T",
        "fixture.mkv",
        "--actor",
        "agent-impl",
        "--size",
        str(len(raw)),
        "--sha256",
        sha,
    )
    update = tmp_path / "updates.json"
    update.write_text(json.dumps([{"path": "src/video.mkv", "binary": staged["binary"]}]))
    run(
        "complete",
        "T",
        "--actor",
        "agent-impl",
        "--check",
        "one",
        "--check",
        "two",
        "--file-updates",
        str(update),
    )
    dest = tmp_path / "src/video.mkv"
    assert dest.read_bytes() == raw
    dest.unlink()
    result = run("effects", "recover")
    assert not result["errors"]
    assert dest.read_bytes() == raw
    assert run("verify")["verify_status"] == "ok"
    dest.unlink()
    blob = tmp_path / ".roadmap/artifacts/file-effects/blobs" / sha
    blob.write_bytes(b"corrupted")
    recovered = run("effects", "recover")
    assert recovered["errors"] and not dest.exists()


def test_staging_cleanup_and_cross_task_separation(tmp_path):
    import pytest

    from esaa.file_effects import stage_file_updates

    source = tmp_path / ".roadmap/binary-input" / hashlib.sha256(b"A").hexdigest()
    source.mkdir(parents=True)
    (source / "same").write_bytes(b"correct")
    digest = hashlib.sha256(b"correct").hexdigest()
    entry = {"path": "src/a", "binary": {"source": "same", "size": 7, "sha256": digest}}
    with pytest.raises(OSError):
        stage_file_updates(tmp_path, [entry], task_id="B")
    missing = {"path": "src/b", "binary": {"source": "missing", "size": 7, "sha256": digest}}
    with pytest.raises(OSError):
        stage_file_updates(tmp_path, [entry, missing], task_id="A")
    assert not list((tmp_path / ".roadmap/staging").iterdir())


def test_binary_metadata_and_artifact_verification_do_not_read_all(tmp_path, monkeypatch):
    from esaa.file_effects import discard_staged, stage_and_compute, verify_artifact

    raw = b"a" * (3 * 1024 * 1024)
    sha = hashlib.sha256(raw).hexdigest()
    source = tmp_path / ".roadmap/binary-input" / hashlib.sha256(b"A").hexdigest()
    source.mkdir(parents=True)
    (source / "in").write_bytes(raw)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/out").write_bytes(raw)
    monkeypatch.setattr(
        Path, "read_bytes", lambda self: (_ for _ in ()).throw(AssertionError("full-file read forbidden"))
    )
    updates = [{"path": "src/out", "binary": {"source": "in", "size": len(raw), "sha256": sha}}]
    staged, effects = stage_and_compute(tmp_path, updates, task_id="A")
    try:
        assert verify_artifact(tmp_path, effects[0]["artifact_path"]) == (True, None)
    finally:
        discard_staged(staged)
