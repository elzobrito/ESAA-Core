"""FIX-1805-QA + FIX-1808-QA — Atomic file effects + content-addressed artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from esaa.file_effects import (
    ARTIFACT_DIR,
    STAGING_DIR,
    cleanup_orphan_staging,
    commit_staged,
    compute_file_metadata,
    discard_staged,
    stage_and_compute,
    stage_file_updates,
    verify_artifact,
    write_artifact,
)

# ----- FIX-1805 atomic effects -----


def test_stage_creates_files_in_staging(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    staged = stage_file_updates(
        tmp_path,
        [
            {"path": "docs/spec/X.md", "content": "# X"},
        ],
    )
    assert len(staged) == 1
    assert Path(staged[0]["staged_path"]).exists()
    # arquivo final ainda nao existe
    assert not (tmp_path / "docs/spec/X.md").exists()


def test_commit_staged_writes_final(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    staged = stage_file_updates(
        tmp_path,
        [
            {"path": "docs/spec/Y.md", "content": "# Y\n"},
        ],
    )
    commit_staged(tmp_path, staged)
    final = tmp_path / "docs/spec/Y.md"
    assert final.exists()
    assert final.read_text(encoding="utf-8") == "# Y\n"


def test_discard_staged_cleans_up(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    staged = stage_file_updates(tmp_path, [{"path": "x.md", "content": "x"}])
    discard_staged(staged)
    assert not Path(staged[0]["staged_path"]).exists()


def test_cleanup_orphan_staging_removes_stale(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    staging = tmp_path / STAGING_DIR
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "stage-9999-orphan.tmp").write_text("x")
    n = cleanup_orphan_staging(tmp_path)
    assert n == 1
    assert not (staging / "stage-9999-orphan.tmp").exists()


# ----- FIX-1808 artifacts + hashes -----


def test_compute_file_metadata_new_file(tmp_path: Path) -> None:
    """Arquivo nao existe -> before_sha256 None; after_sha256 calculado."""
    meta = compute_file_metadata(tmp_path, "src/x.py", "print('hi')\n")
    assert meta["before_sha256"] is None
    assert meta["after_sha256"] == hashlib.sha256(b"print('hi')\n").hexdigest()
    assert meta["bytes"] == len(b"print('hi')\n")
    assert meta["encoding"] == "utf-8"


def test_compute_file_metadata_existing_file(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("old", encoding="utf-8")
    meta = compute_file_metadata(tmp_path, "f.txt", "new")
    assert meta["before_sha256"] == hashlib.sha256(b"old").hexdigest()
    assert meta["after_sha256"] == hashlib.sha256(b"new").hexdigest()


def test_write_artifact_content_addressed(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "src/x.py", "x = 1\n")
    out = write_artifact(tmp_path, meta, "x = 1\n")
    assert out["artifact_sha256"]
    assert out["artifact_path"].startswith(ARTIFACT_DIR)
    p = tmp_path / out["artifact_path"]
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["content"] == "x = 1\n"
    assert data["after_sha256"] == meta["after_sha256"]


def test_verify_artifact_ok(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "x.md", "ok\n")
    out = write_artifact(tmp_path, meta, "ok\n")
    ok, err = verify_artifact(tmp_path, out["artifact_path"])
    assert ok is True
    assert err is None


def test_verify_artifact_missing(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    ok, err = verify_artifact(tmp_path, ".roadmap/artifacts/file-effects/nonexistent.json")
    assert ok is False
    assert err == "ARTIFACT_MISSING"


def test_verify_artifact_hash_mismatch(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    meta = compute_file_metadata(tmp_path, "x.md", "ok\n")
    out = write_artifact(tmp_path, meta, "ok\n")
    p = tmp_path / out["artifact_path"]
    data = json.loads(p.read_text(encoding="utf-8"))
    # corrompe o content sem atualizar after_sha256
    data["content"] = "TAMPERED"
    p.write_text(json.dumps(data), encoding="utf-8")
    ok, err = verify_artifact(tmp_path, out["artifact_path"])
    assert ok is False
    # Hash do payload muda quando content muda; pode ser ARTIFACT_HASH_MISMATCH
    # OU ARTIFACT_CONTENT_HASH_MISMATCH dependendo de qual check pega primeiro.
    assert err in {"ARTIFACT_HASH_MISMATCH", "ARTIFACT_CONTENT_HASH_MISMATCH"}


def test_stage_and_compute_combines_steps(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    staged, metas = stage_and_compute(
        tmp_path,
        [
            {"path": "a.md", "content": "A"},
            {"path": "b.md", "content": "B"},
        ],
    )
    assert len(staged) == 2
    assert len(metas) == 2
    for m in metas:
        assert "artifact_sha256" in m
        assert "after_sha256" in m
