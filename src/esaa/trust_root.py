"""External trust pin and monotonic checkpoint (hotfix 002).

The pin lives outside the project, under ESAA_TRUST_ROOT. Workspace
`.roadmap/governance-anchor.json` is a replica: it is never copied into the
trust root automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import ESAAError
from .identity import ALG, ANCHOR_REL, load_anchor, project_registry, public_key_fingerprint

ENV_TRUST_ROOT = "ESAA_TRUST_ROOT"
PIN_SCHEMA = "esaa.identity.trust.v1"
EPOCH = "esaa.identity.v1"


def resolve_trust_root() -> Path | None:
    raw = (os.environ.get(ENV_TRUST_ROOT) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def bound_record_path(root: Path) -> Path:
    base = resolve_trust_root()
    if base is None:
        raise ESAAError(
            "BLOCKED_ENVIRONMENT",
            "activation requires ESAA_TRUST_ROOT pointing outside the project",
        )
    project = root.resolve()
    if _is_inside(base, project):
        raise ESAAError(
            "BLOCKED_ENVIRONMENT",
            "ESAA_TRUST_ROOT must be outside the project workspace",
        )
    digest = hashlib.sha256(str(project).encode("utf-8")).hexdigest()
    return base / f"{digest}.json"


def try_load_record(root: Path) -> dict[str, Any] | None:
    if resolve_trust_root() is None:
        return None
    path = bound_record_path(root)
    if not path.is_file():
        return None
    return _read_record(path)


def import_trust_pin(root: Path, pin: dict[str, Any]) -> dict[str, Any]:
    """Owner-authorized import. Does not read workspace governance-anchor.json."""
    record = _normalize_pin(pin)
    path = bound_record_path(root)
    existing = _read_record(path) if path.is_file() else None
    if existing is not None:
        if existing["fingerprint_sha256"] != record["fingerprint_sha256"]:
            raise ESAAError("TRUST_MISMATCH", "an owner pin already exists for this workspace")
        if existing["checkpoint"]["event_seq"] > record["checkpoint"]["event_seq"]:
            raise ESAAError("TRUST_ROLLBACK", "imported checkpoint would regress the external pin")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_record(path, record)
    return record


def require_pin_record(root: Path) -> dict[str, Any]:
    """Owner pin must exist. Does not inspect the workspace replica."""
    if resolve_trust_root() is None:
        raise ESAAError(
            "BLOCKED_ENVIRONMENT",
            "activation requires ESAA_TRUST_ROOT pointing outside the project",
        )
    record = try_load_record(root)
    if record is None:
        raise ESAAError(
            "BLOCKED_ENVIRONMENT",
            "no owner-imported trust pin for this workspace",
        )
    return record


def require_pin_for_activation(root: Path) -> dict[str, Any]:
    record = require_pin_record(root)
    anchor = load_anchor(root)
    if (
        record["public_key_hex"] != anchor["public_key_hex"]
        or record["fingerprint_sha256"] != anchor["fingerprint_sha256"]
    ):
        raise ESAAError("TRUST_MISMATCH", "workspace anchor does not match the external pin")
    return record


def evaluate_trust(root: Path, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    registry = project_registry(events)
    last_seq = int(events[-1]["event_seq"]) if events else 0
    record = try_load_record(root)

    if registry["active"]:
        if resolve_trust_root() is None:
            raise ESAAError(
                "BLOCKED_ENVIRONMENT",
                "activation requires ESAA_TRUST_ROOT pointing outside the project",
            )
        if record is None:
            raise ESAAError(
                "BLOCKED_ENVIRONMENT",
                "no owner-imported trust pin for this workspace",
            )
        bootstrap = registry["bootstrap"]
        if (
            record["public_key_hex"] != bootstrap["public_key_hex"]
            or record["fingerprint_sha256"] != bootstrap["fingerprint_sha256"]
            or record["project_id"] != bootstrap["fingerprint_sha256"]
        ):
            raise ESAAError("TRUST_MISMATCH", "external pin does not match bootstrapped authority")
        if record["epoch"] != EPOCH:
            raise ESAAError("AUTH_EPOCH_UNSUPPORTED", "unsupported trust pin epoch")
        checkpoint = record["checkpoint"]
        _assert_monotonic_checkpoint(checkpoint, events)
        pinned_bootstrap = checkpoint.get("bootstrap_event_seq")
        if pinned_bootstrap is not None and int(bootstrap["event_seq"]) != int(pinned_bootstrap):
            raise ESAAError("TRUST_ROLLBACK", "bootstrap event_seq diverges from the external checkpoint")
        if not (root / ANCHOR_REL).is_file():
            raise ESAAError("ANCHOR_MISSING", f"protected public replica missing: {ANCHOR_REL}")
        anchor = load_anchor(root)
        if (
            anchor["public_key_hex"] != record["public_key_hex"]
            or anchor["fingerprint_sha256"] != record["fingerprint_sha256"]
        ):
            raise ESAAError("ANCHOR_MISMATCH", "workspace anchor does not match the external pin")
        return record

    if record is not None and record["checkpoint"].get("bootstrap_event_seq") is not None:
        raise ESAAError("TRUST_ROLLBACK", "bootstrapped authority was removed from the event store")
    return record


def advance_checkpoint(
    root: Path,
    events: list[dict[str, Any]],
    projection_hash_sha256: str,
) -> dict[str, Any] | None:
    record = try_load_record(root)
    if record is None:
        return None
    evaluate_trust(root, events)
    last_seq = int(events[-1]["event_seq"]) if events else 0
    checkpoint = record["checkpoint"]
    if last_seq < int(checkpoint["event_seq"]):
        raise ESAAError("TRUST_ROLLBACK", "refusing to regress the external checkpoint")
    stored_hash = checkpoint.get("projection_hash_sha256")
    if stored_hash and last_seq == int(checkpoint["event_seq"]) and stored_hash != projection_hash_sha256:
        raise ESAAError("TRUST_MISMATCH", "projection hash diverges from the external checkpoint")
    registry = project_registry(events)
    if registry["active"]:
        bootstrap_seq = int(registry["bootstrap"]["event_seq"])
        pinned = checkpoint.get("bootstrap_event_seq")
        if pinned is not None and int(pinned) != bootstrap_seq:
            raise ESAAError("TRUST_ROLLBACK", "bootstrap event_seq diverges from the external checkpoint")
        checkpoint["bootstrap_event_seq"] = bootstrap_seq
        record["project_id"] = registry["bootstrap"]["fingerprint_sha256"]
    checkpoint["event_seq"] = last_seq
    checkpoint["projection_hash_sha256"] = projection_hash_sha256
    _write_record(bound_record_path(root), record)
    return record


def catch_up_checkpoint(
    root: Path,
    events: list[dict[str, Any]],
    projection_hash_sha256: str,
) -> dict[str, Any] | None:
    """Advance a lagging pin after a successful parse. Never writes on dry-run."""
    try:
        advance_checkpoint(root, events, projection_hash_sha256)
    except ESAAError as exc:
        last_seq = int(events[-1]["event_seq"]) if events else 0
        return {
            "verify_status": "corrupted",
            "error_code": exc.code,
            "error_message": exc.message,
            "last_event_seq": last_seq,
            "projection_hash_sha256": projection_hash_sha256,
        }
    return None


def make_pin(*, public_key_hex: str, epoch: str = EPOCH) -> dict[str, Any]:
    public_key_hex = public_key_hex.strip().lower()
    fingerprint = public_key_fingerprint(public_key_hex)
    return {
        "schema_version": PIN_SCHEMA,
        "alg": ALG,
        "epoch": epoch,
        "project_id": fingerprint,
        "public_key_hex": public_key_hex,
        "fingerprint_sha256": fingerprint,
        "checkpoint": {
            "event_seq": 0,
            "projection_hash_sha256": None,
            "bootstrap_event_seq": None,
        },
    }


def _projection_hash_of(events: list[dict[str, Any]]) -> str:
    from .projector import materialize

    roadmap, _, _ = materialize(events)
    return roadmap["meta"]["run"]["projection_hash_sha256"]


def _assert_monotonic_checkpoint(checkpoint: dict[str, Any], events: list[dict[str, Any]]) -> None:
    last_seq = int(events[-1]["event_seq"]) if events else 0
    checkpoint_seq = int(checkpoint["event_seq"])
    if checkpoint_seq > last_seq:
        raise ESAAError("TRUST_ROLLBACK", "event store seq is behind the external checkpoint")
    stored_hash = checkpoint.get("projection_hash_sha256")
    if not stored_hash:
        return
    if last_seq == checkpoint_seq:
        if _projection_hash_of(events) != stored_hash:
            raise ESAAError("TRUST_MISMATCH", "projection hash diverges from the external checkpoint")
        return
    prefix = [event for event in events if int(event["event_seq"]) <= checkpoint_seq]
    if _projection_hash_of(prefix) != stored_hash:
        raise ESAAError("TRUST_MISMATCH", "historical prefix diverges from the external checkpoint")


def _is_inside(path: Path, container: Path) -> bool:
    try:
        path.resolve().relative_to(container.resolve())
        return True
    except ValueError:
        return False


def _normalize_pin(pin: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pin, dict):
        raise ESAAError("INVALID_ARGUMENT", "trust pin must be a JSON object")
    schema = str(pin.get("schema_version") or "").strip()
    if schema != PIN_SCHEMA:
        raise ESAAError("AUTH_EPOCH_UNSUPPORTED", f"unsupported trust pin schema: {schema or '<missing>'}")
    epoch = str(pin.get("epoch") or "").strip()
    if epoch != EPOCH:
        raise ESAAError("AUTH_EPOCH_UNSUPPORTED", f"unsupported trust pin epoch: {epoch or '<missing>'}")
    alg = str(pin.get("alg") or "").strip().lower()
    if alg != ALG:
        raise ESAAError("ACTOR_AUTH_FAILED", f"unsupported trust pin alg: {alg or '<missing>'}")
    public_key_hex = str(pin.get("public_key_hex") or "").strip().lower()
    fingerprint = public_key_fingerprint(public_key_hex)
    declared = str(pin.get("fingerprint_sha256") or "").strip().lower()
    if declared and declared != fingerprint:
        raise ESAAError("TRUST_MISMATCH", "trust pin fingerprint does not match public key")
    project_id = str(pin.get("project_id") or fingerprint).strip().lower()
    if project_id != fingerprint:
        raise ESAAError("TRUST_MISMATCH", "trust pin project_id must equal the public-key fingerprint")
    checkpoint = pin.get("checkpoint") or {}
    if not isinstance(checkpoint, dict):
        raise ESAAError("INVALID_ARGUMENT", "trust pin checkpoint must be an object")
    event_seq = int(checkpoint.get("event_seq") or 0)
    if event_seq < 0:
        raise ESAAError("INVALID_ARGUMENT", "checkpoint event_seq must be >= 0")
    bootstrap_seq = checkpoint.get("bootstrap_event_seq")
    if bootstrap_seq is not None:
        bootstrap_seq = int(bootstrap_seq)
    projection_hash = checkpoint.get("projection_hash_sha256")
    if projection_hash is not None:
        projection_hash = str(projection_hash).strip().lower() or None
    return {
        "schema_version": PIN_SCHEMA,
        "alg": ALG,
        "epoch": epoch,
        "project_id": project_id,
        "public_key_hex": public_key_hex,
        "fingerprint_sha256": fingerprint,
        "checkpoint": {
            "event_seq": event_seq,
            "projection_hash_sha256": projection_hash,
            "bootstrap_event_seq": bootstrap_seq,
        },
    }


def _read_record(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ESAAError("TRUST_MISMATCH", "trust pin is not valid JSON") from exc
    return _normalize_pin(data)


def _write_record(path: Path, record: dict[str, Any]) -> None:
    payload = json.dumps(_normalize_pin(record), ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".esaa-trust-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
