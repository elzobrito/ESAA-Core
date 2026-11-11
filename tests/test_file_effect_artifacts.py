"""FIX-1808-QA — File effect artifact auditability (content-addressed)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from esaa.file_effects import (
    ARTIFACT_DIR,
    compute_file_metadata,
    verify_artifact,
    write_artifact,
)


def test_artifact_created_with_content_addressed_path(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "src/x.py", "x = 1\n")
    out = write_artifact(tmp_path, meta, "x = 1\n")
    p = tmp_path / out["artifact_path"]
    assert p.exists()
    assert out["artifact_sha256"] in str(p)


def test_before_after_hash_for_new_file(tmp_path: Path) -> None:
    meta = compute_file_metadata(tmp_path, "src/x.py", "abc\n")
    assert meta["before_sha256"] is None
    assert meta["after_sha256"] == hashlib.sha256(b"abc\n").hexdigest()


def test_before_after_hash_for_existing_file(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("before", encoding="utf-8")
    meta = compute_file_metadata(tmp_path, "f.txt", "after")
    assert meta["before_sha256"] == hashlib.sha256(b"before").hexdigest()
    assert meta["after_sha256"] == hashlib.sha256(b"after").hexdigest()


def test_bytes_and_encoding_in_metadata(tmp_path: Path) -> None:
    meta = compute_file_metadata(tmp_path, "x.md", "ola\n")
    expected_bytes = len(b"ola\n")
    assert meta["bytes"] == expected_bytes
    assert meta["encoding"] == "utf-8"


def test_verify_artifact_succeeds_for_clean_artifact(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "x.md", "ok\n")
    out = write_artifact(tmp_path, meta, "ok\n")
    ok, err = verify_artifact(tmp_path, out["artifact_path"])
    assert ok is True
    assert err is None


def test_missing_artifact_detected(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    ok, err = verify_artifact(tmp_path, f"{ARTIFACT_DIR}/nonexistent.json")
    assert ok is False
    assert err == "ARTIFACT_MISSING"


def test_tampered_artifact_detected(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "x.md", "ok\n")
    out = write_artifact(tmp_path, meta, "ok\n")
    p = tmp_path / out["artifact_path"]
    data = json.loads(p.read_text(encoding="utf-8"))
    data["content"] = "TAMPERED"
    p.write_text(json.dumps(data), encoding="utf-8")
    ok, err = verify_artifact(tmp_path, out["artifact_path"])
    assert ok is False
    assert err in {"ARTIFACT_HASH_MISMATCH", "ARTIFACT_CONTENT_HASH_MISMATCH"}
