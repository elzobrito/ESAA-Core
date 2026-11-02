"""FIX-1805 / FIX-1808 — Atomic file effects + content-addressed artifacts.



API:

- stage_file_updates(root, file_updates) -> staged list

- commit_staged(staged)                  -> apply to final paths

- discard_staged(staged)                 -> cleanup on failure

- cleanup_orphan_staging(root)           -> sweep abandoned staged files

- compute_file_metadata(root, path, content) -> {before/after sha256, bytes, encoding}

- write_artifact(root, metadata, content) -> artifact_path (content-addressed)

- verify_artifact(root, artifact_path)   -> bool, mismatch details

"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGING_DIR = ".roadmap/staging"

ARTIFACT_DIR = ".roadmap/artifacts/file-effects"


def _utc_now_iso() -> str:

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:

    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    from .binary_payload import _open_confined

    fd = _open_confined(path.parent, path.name)
    digest = hashlib.sha256()
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("hash source must be a single-link regular file")
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def stage_file_updates(
    root: Path, file_updates: list[dict[str, str]], task_id: str | None = None
) -> list[dict[str, Any]]:
    """Stage file_updates em .roadmap/staging/. Returns list of staged records."""

    staging_root = root / STAGING_DIR

    staging_root.mkdir(parents=True, exist_ok=True)

    staged: list[dict[str, Any]] = []
    try:
        for i, item in enumerate(file_updates):
            final_path = item["path"].replace("\\", "/")
            if "binary" in item:
                from .binary_payload import stage_binary

                binary = item["binary"]
                if not task_id:
                    raise ValueError("binary update requires task identity")
                task_key = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
                source_root = root / ".roadmap" / "binary-input" / task_key
                staged_path = stage_binary(
                    source_root,
                    binary["source"],
                    staging_root,
                    size=binary["size"],
                    sha256=binary["sha256"],
                    limit=binary["size"],
                )
                staged.append(
                    {
                        "final_path": final_path,
                        "staged_path": str(staged_path),
                        "binary": binary,
                        "final_abs_path": item.get("_esaa_final_abs_path"),
                        "effect_scope": item.get("_esaa_effect_scope", "workspace"),
                        "source_path": item.get("_esaa_source_path", final_path),
                        "target": item.get("_esaa_target"),
                        "target_root": item.get("_esaa_target_root"),
                        "target_path": item.get("_esaa_target_path"),
                    }
                )
                continue
            content = item["content"]
            # Each submission owns its stage, even when another delivery has identical bytes.
            fd, staged_name = tempfile.mkstemp(prefix=f"stage-{i:04d}-", suffix=".tmp", dir=staging_root)
            staged_path = Path(staged_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)
            except BaseException:
                staged_path.unlink(missing_ok=True)
                raise
            staged.append(
                {
                    "final_path": final_path,
                    "staged_path": str(staged_path),
                    "content": content,
                    "final_abs_path": item.get("_esaa_final_abs_path"),
                    "effect_scope": item.get("_esaa_effect_scope", "workspace"),
                    "source_path": item.get("_esaa_source_path", final_path),
                    "target": item.get("_esaa_target"),
                    "target_root": item.get("_esaa_target_root"),
                    "target_path": item.get("_esaa_target_path"),
                }
            )
    except BaseException:
        discard_staged(staged)
        raise
    return staged


def commit_staged(root: Path, staged: list[dict[str, Any]]) -> None:
    """Atomically apply the validated in-memory content, never a mutable stage copy."""
    from .binary_artifacts import assert_safe_destination

    for entry in staged:
        final = Path(entry["final_abs_path"]) if entry.get("final_abs_path") else root / entry["final_path"]
        final.parent.mkdir(parents=True, exist_ok=True)
        assert_safe_destination(final)
        if "binary" in entry:
            from .binary_artifacts import restore_blob

            binary = entry["binary"]
            try:
                restore_blob(
                    root / ARTIFACT_DIR / "blobs",
                    binary["sha256"],
                    final,
                    size=binary["size"],
                    limit=binary["size"],
                )
            finally:
                Path(entry["staged_path"]).unlink(missing_ok=True)
            continue
        fd, name = tempfile.mkstemp(prefix=".esaa-apply-", suffix=".tmp", dir=final.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                if os.name != "nt" and final.exists():
                    os.fchmod(handle.fileno(), stat.S_IMODE(final.stat().st_mode))
                handle.write(entry["content"].encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, final)
        finally:
            temporary.unlink(missing_ok=True)
            Path(entry["staged_path"]).unlink(missing_ok=True)


def discard_staged(staged: list[dict[str, Any]]) -> None:
    """Cleanup staged files on failure."""

    for entry in staged:

        try:

            Path(entry["staged_path"]).unlink()

        except FileNotFoundError:

            pass


def cleanup_orphan_staging(root: Path) -> int:
    """Remove arquivos staged abandonados. Returns count removed."""

    staging_root = root / STAGING_DIR

    if not staging_root.exists():

        return 0

    n = 0

    for p in staging_root.glob("stage-*.tmp"):

        try:

            p.unlink()

            n += 1

        except OSError:

            pass

    return n


def compute_file_metadata(
    root: Path,
    path: str,
    after_content: str,
    encoding: str = "utf-8",
    final_abs_path: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Computa metadados de auditoria para um file_update."""

    final = Path(final_abs_path) if final_abs_path else root / path

    if final.exists():

        before = final.read_bytes()

        before_sha = _sha256_bytes(before)

    else:

        before_sha = None

    after_bytes = after_content.encode(encoding)

    meta = {
        "path": path,
        "before_sha256": before_sha,
        "after_sha256": _sha256_bytes(after_bytes),
        "bytes": len(after_bytes),
        "encoding": encoding,
    }
    if final_abs_path:
        meta["absolute_path"] = str(final)
    if extra:
        for key, value in extra.items():
            if value is not None:
                meta[key] = value
    return meta


def _canonical_artifact_hash(payload: dict[str, Any]) -> str:
    """Hash determinístico do payload SEM o próprio artifact_sha256."""

    p = {k: v for k, v in payload.items() if k != "artifact_sha256"}

    canon = json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    return _sha256_bytes(canon.encode("utf-8"))


def write_artifact(root: Path, metadata: dict[str, Any], content: str) -> dict[str, Any]:
    """Grava artifact content-addressed e devolve metadata atualizada com

    artifact_sha256 e artifact_path."""

    artifact_root = root / ARTIFACT_DIR

    artifact_root.mkdir(parents=True, exist_ok=True)

    payload = dict(metadata)
    payload.update(
        {
            "artifact_id": f"ART-{metadata['after_sha256']}",
            "content": content,
            "ts": _utc_now_iso(),
        }
    )

    artifact_sha = _canonical_artifact_hash(payload)

    payload["artifact_sha256"] = artifact_sha

    artifact_filename = f"{artifact_sha}.json"

    artifact_path = artifact_root / artifact_filename

    if not artifact_path.exists():

        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    out = dict(metadata)

    out["artifact_sha256"] = artifact_sha

    out["artifact_path"] = f"{ARTIFACT_DIR}/{artifact_filename}"

    return out


def verify_artifact(root: Path, artifact_path: str) -> tuple[bool, str | None]:
    """Verifica que o artifact existe e tem hash consistente.

    Returns (ok, error_code|None).

    """

    p = root / artifact_path

    if not p.exists():

        return False, "ARTIFACT_MISSING"

    try:

        data = json.loads(p.read_text(encoding="utf-8"))

    except json.JSONDecodeError:

        return False, "ARTIFACT_INVALID_JSON"

    declared = data.get("artifact_sha256")

    if not declared:

        return False, "ARTIFACT_NO_HASH"

    computed = _canonical_artifact_hash(data)

    if computed != declared:

        return False, "ARTIFACT_HASH_MISMATCH"

    # Reconfere after_sha256 do content

    content = data.get("content", "")

    enc = data.get("encoding", "utf-8")

    if enc == "binary":
        try:
            blob = root / ARTIFACT_DIR / "blobs" / data["after_sha256"]
            if blob.is_symlink() or blob.stat().st_size != data["bytes"]:
                return False, "ARTIFACT_CONTENT_HASH_MISMATCH"
            if _sha256_file(blob) != data["after_sha256"]:
                return False, "ARTIFACT_CONTENT_HASH_MISMATCH"
        except (OSError, ValueError, KeyError):
            return False, "ARTIFACT_CONTENT_HASH_MISMATCH"
        return True, None
    if _sha256_bytes(content.encode(enc)) != data.get("after_sha256"):

        return False, "ARTIFACT_CONTENT_HASH_MISMATCH"

    return True, None


def read_artifact(root: Path, artifact_path: str) -> dict[str, Any]:
    ok, error = verify_artifact(root, artifact_path)
    if not ok:
        raise ValueError(error or "ARTIFACT_INVALID")
    return json.loads((root / artifact_path).read_text(encoding="utf-8"))


def _safe_rel_path(path: str) -> str:
    norm = path.replace("\\", "/").strip()
    parts = [part for part in norm.split("/") if part]
    if not norm or norm.startswith("/") or any(part == ".." for part in parts):
        raise ValueError(f"unsafe artifact path: {path}")
    return "/".join(parts)


def recover_file_effects(root: Path, events: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    latest_by_path: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("action") != "orchestrator.file.write":
            continue
        for effect in event.get("payload", {}).get("effects", []) or []:
            path = effect.get("path")
            if path and effect.get("artifact_path"):
                latest_by_path[path] = effect

    recovered: list[str] = []
    already_applied: list[str] = []
    errors: list[dict[str, str]] = []

    for path, effect in sorted(latest_by_path.items()):
        try:
            artifact = read_artifact(root, effect["artifact_path"])
            rel_path = _safe_rel_path(artifact.get("target_path") or artifact["path"])
            if artifact.get("effect_scope") == "external":
                target_root = Path(artifact["target_root"]).resolve()
                final = Path(artifact["absolute_path"]).resolve()
                final.relative_to(target_root)
            else:
                final = root / rel_path
            after_sha = artifact["after_sha256"]
            if final.exists() and _sha256_bytes(final.read_bytes()) == after_sha:
                already_applied.append(rel_path)
                continue
            if not dry_run:
                final.parent.mkdir(parents=True, exist_ok=True)
                if artifact.get("encoding") == "binary":
                    from .binary_artifacts import restore_blob

                    restore_blob(
                        root / ARTIFACT_DIR / "blobs",
                        after_sha,
                        final,
                        size=artifact["bytes"],
                        limit=artifact["bytes"],
                    )
                else:
                    final.write_bytes(artifact.get("content", "").encode(artifact.get("encoding", "utf-8")))
            recovered.append(rel_path)
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)})

    return {
        "status": "dry_run" if dry_run else "recovered",
        "files_recovered": len(recovered),
        "files_already_applied": len(already_applied),
        "errors": errors,
        "recovered": recovered,
        "already_applied": already_applied,
    }


def stage_and_compute(
    root: Path, file_updates: list[dict[str, str]], task_id: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Atomico: stage + compute metadata + write_artifact em uma chamada.

    Returns (staged_list, metadata_list).

    """

    staged = stage_file_updates(root, file_updates, task_id=task_id)

    metadata_list: list[dict[str, Any]] = []

    try:
        for entry in staged:

            extra = {
                "effect_scope": entry.get("effect_scope", "workspace"),
                "source_path": entry.get("source_path"),
                "target": entry.get("target"),
                "target_root": entry.get("target_root"),
                "target_path": entry.get("target_path"),
            }
            if "binary" in entry:
                from .binary_artifacts import store_blob

                binary = entry["binary"]
                staged_path = Path(entry["staged_path"])
                store_blob(
                    staged_path.parent,
                    staged_path.name,
                    root / ARTIFACT_DIR / "blobs",
                    size=binary["size"],
                    sha256=binary["sha256"],
                    limit=binary["size"],
                )
                final = (
                    Path(entry["final_abs_path"])
                    if entry.get("final_abs_path")
                    else root / entry["final_path"]
                )
                before = _sha256_file(final) if final.exists() else None
                meta = {
                    "path": entry["final_path"],
                    "before_sha256": before,
                    "after_sha256": binary["sha256"],
                    "bytes": binary["size"],
                    "encoding": "binary",
                }
                meta.update({k: v for k, v in extra.items() if v is not None})
                if entry.get("final_abs_path"):
                    meta["absolute_path"] = entry["final_abs_path"]
                metadata_list.append(write_artifact(root, meta, ""))
                continue
            meta = compute_file_metadata(
                root,
                entry["final_path"],
                entry["content"],
                final_abs_path=entry.get("final_abs_path"),
                extra=extra,
            )

            meta = write_artifact(root, meta, entry["content"])

            metadata_list.append(meta)

    except BaseException:
        discard_staged(staged)
        raise

    return staged, metadata_list
