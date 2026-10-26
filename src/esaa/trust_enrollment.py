"""Owner enrollment discovery independent of the caller's environment.

Only public bindings live here. The owner must protect this host directory
outside every enrolled workspace and deny agent write access to it.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import ESAAError


def registry_directory() -> Path:
    """Resolve the operating-system profile, never HOME/XDG or a caller override."""
    if os.name == "nt":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        loader = getattr(ctypes, "windll", None)
        if loader is None or loader.shell32.SHGetFolderPathW(None, 0x001C, None, 0, buffer):
            raise ESAAError("BLOCKED_ENVIRONMENT", "cannot resolve protected OS user profile")
        return Path(buffer.value) / "ESAA" / "trust-enrollments"
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/esaa/trust-enrollments"


def enrollment_path(root: Path) -> Path:
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    return registry_directory() / f"{key}.json"


def read_enrollment(root: Path) -> dict[str, Any] | None:
    path = enrollment_path(root)
    if path.is_symlink():
        raise ESAAError("TRUST_MISMATCH", "owner enrollment cannot be a symlink")
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 16384:
            raise ValueError("oversized record")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "esaa.trust.enrollment.v1":
            raise ValueError("unknown schema")
        if value.get("workspace") != str(root.resolve()):
            raise ValueError("workspace mismatch")
        if not isinstance(value.get("trust_root"), str) or not isinstance(value.get("fingerprint"), str):
            raise ValueError("invalid binding")
    except (OSError, ValueError) as exc:
        raise ESAAError("TRUST_MISMATCH", "invalid protected owner enrollment") from exc
    return value


def validate_enrollment(root: Path, trust_root: Path | None) -> dict[str, Any] | None:
    existing = read_enrollment(root)
    if existing is not None:
        if trust_root is None:
            raise ESAAError("BLOCKED_ENVIRONMENT", "enrolled workspace lost ESAA_TRUST_ROOT")
        if str(trust_root.resolve()) != existing["trust_root"]:
            raise ESAAError("TRUST_MISMATCH", "trust root differs from protected owner enrollment")
    return existing


def enroll(root: Path, trust_root: Path, fingerprint: str) -> None:
    existing = validate_enrollment(root, trust_root)
    if existing is not None:
        if existing["fingerprint"] != fingerprint:
            raise ESAAError("TRUST_MISMATCH", "owner enrollment authority cannot be replaced")
        return
    path = enrollment_path(root)
    if path.resolve().is_relative_to(root.resolve()):
        raise ESAAError("BLOCKED_ENVIRONMENT", "owner enrollment must be outside the workspace")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise ESAAError("BLOCKED_ENVIRONMENT", "owner enrollment directory cannot be a symlink")
    value = {
        "schema": "esaa.trust.enrollment.v1",
        "workspace": str(root.resolve()),
        "trust_root": str(trust_root.resolve()),
        "fingerprint": fingerprint,
    }
    fd, name = tempfile.mkstemp(prefix=".enrollment-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
