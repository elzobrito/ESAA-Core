"""Orchestrator-owned bounded logs and digest-verified result lookup."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .utils import sha256_hex


def result_digest(payload: dict[str, Any]) -> str:
    return sha256_hex({k: v for k, v in payload.items() if k != "result_sha256"})


def _artifact(root: Path, relative: str, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ESAAError("VERIFICATION_FAILED", "invalid run ID")
    base = root / ".roadmap/artifacts/verification" / run_id
    path = root / relative
    if not path.resolve().is_relative_to(base.resolve()):
        raise ESAAError("VERIFICATION_FAILED", "invalid log path")
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ESAAError("VERIFICATION_FAILED", "symlinked verification artifact")
    return path


def save_logs(root: Path, run_id: str, results: list[dict[str, Any]]) -> None:
    for result in results:
        logs = {}
        for stream in ("stdout", "stderr"):
            rel = f".roadmap/artifacts/verification/{run_id}/{result['id']}.{stream}.log"
            path = _artifact(root, rel, run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = result.pop(stream).encode("utf-8")
            path.write_bytes(data)
            logs[stream] = {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        result["logs"] = logs


def find_result(root: Path, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    for event in reversed(events):
        if event["action"] == "verification.run" and event["payload"].get("run_id") == run_id:
            payload = event["payload"]
            if event["actor"] != "orchestrator" or payload.get("result_sha256") != result_digest(payload):
                raise ESAAError("VERIFICATION_FAILED", "verification result integrity failure")
            for result in payload["results"]:
                for log in result["logs"].values():
                    path = _artifact(root, log["path"], run_id)
                    if (
                        not path.is_file()
                        or path.stat().st_size != log["bytes"]
                        or hashlib.sha256(path.read_bytes()).hexdigest() != log["sha256"]
                    ):
                        raise ESAAError("VERIFICATION_FAILED", "verification log missing or altered")
            return payload
    raise ESAAError("VERIFICATION_REQUIRED", "verification execution ID not found")
