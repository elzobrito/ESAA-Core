"""Authenticated actor registry and privileged-operation authorization.

The identity contract is inactive until an `actor.bootstrap` event exists.
Historical workspaces without that event keep the pre-contract review path.

Private owner credentials are never generated or stored by this module.
Tests mint fixture keys in temporary directories only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .errors import ESAAError
from .utils import canonical_json_bytes

ALG = "ed25519"
ANCHOR_REL = ".roadmap/governance-anchor.json"
RESERVED_ACTOR_IDS = frozenset({"orchestrator"})
REGISTERABLE_ROLES = frozenset({"qa", "specification", "implementation"})
REVIEW_ROLES = frozenset({"qa"})
PRIVILEGED_OPERATIONS = frozenset({"actor.bootstrap", "actor.register", "review"})


def public_key_fingerprint(public_key_hex: str) -> str:
    raw = _parse_hex(public_key_hex, "public_key_hex")
    return hashlib.sha256(raw).hexdigest()


def load_anchor(root: Path) -> dict[str, str]:
    path = root / ANCHOR_REL
    if not path.is_file():
        raise ESAAError("ANCHOR_MISSING", f"protected public anchor missing: {ANCHOR_REL}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ESAAError("ANCHOR_MISMATCH", "governance-anchor.json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ESAAError("ANCHOR_MISMATCH", "governance-anchor.json must be an object")
    public_key_hex = str(data.get("public_key_hex") or "").strip().lower()
    if not public_key_hex:
        raise ESAAError("ANCHOR_MISMATCH", "governance-anchor.json missing public_key_hex")
    fingerprint = public_key_fingerprint(public_key_hex)
    declared = str(data.get("fingerprint_sha256") or "").strip().lower()
    if declared and declared != fingerprint:
        raise ESAAError("ANCHOR_MISMATCH", "governance-anchor fingerprint does not match public key")
    alg = str(data.get("alg") or ALG).strip().lower()
    if alg != ALG:
        raise ESAAError("ANCHOR_MISMATCH", f"unsupported anchor alg: {alg}")
    return {
        "alg": ALG,
        "public_key_hex": public_key_hex,
        "fingerprint_sha256": fingerprint,
        "path": ANCHOR_REL,
    }


def canonical_authorization_payload(
    *,
    operation: str,
    project_id: str,
    nonce: str,
    scope: dict[str, Any],
) -> dict[str, Any]:
    if operation not in PRIVILEGED_OPERATIONS:
        raise ESAAError("INVALID_ARGUMENT", f"unsupported authorization operation: {operation}")
    nonce = nonce.strip().lower()
    if len(nonce) < 32 or any(c not in "0123456789abcdef" for c in nonce):
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization nonce must be lowercase hex (>=16 bytes)")
    return {
        "alg": ALG,
        "nonce": nonce,
        "operation": operation,
        "project_id": project_id.strip().lower(),
        "scope": scope,
    }


def verify_signature(public_key_hex: str, payload: dict[str, Any], signature_hex: str) -> None:
    public_raw = _parse_hex(public_key_hex, "public_key_hex")
    signature = _parse_hex(signature_hex, "signature_hex")
    try:
        key = Ed25519PublicKey.from_public_bytes(public_raw)
        key.verify(signature, canonical_json_bytes(payload))
    except (ValueError, InvalidSignature) as exc:
        raise ESAAError("AUTH_SIGNATURE_INVALID", "authorization signature is invalid") from exc


def load_authorization(blob: Any) -> dict[str, Any]:
    if not isinstance(blob, dict):
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization must be a JSON object")
    payload = blob.get("payload")
    signature_hex = str(blob.get("signature_hex") or "").strip().lower()
    if not isinstance(payload, dict) or not signature_hex:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization requires payload and signature_hex")
    for field in ("alg", "nonce", "operation", "project_id", "scope"):
        if field not in payload:
            raise ESAAError("ACTOR_AUTH_FAILED", f"authorization payload missing {field}")
    if not isinstance(payload["scope"], dict):
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization scope must be an object")
    if set(blob) != {"payload", "signature_hex"} or set(payload) != {"alg", "nonce", "operation", "project_id", "scope"}:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization has unknown fields")
    if not all(isinstance(payload[k], str) for k in ("alg", "nonce", "operation", "project_id")):
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization fields must be strings")
    if not isinstance(blob["signature_hex"], str):
        raise ESAAError("ACTOR_AUTH_FAILED", "signature must be a string")
    canonical = canonical_authorization_payload(operation=payload["operation"],
        project_id=payload["project_id"], nonce=payload["nonce"], scope=payload["scope"])
    if payload != canonical:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization payload is not canonical")
    _parse_hex(signature_hex, "signature_hex")
    return {
        "payload": {
            "alg": str(payload["alg"]),
            "nonce": str(payload["nonce"]).strip().lower(),
            "operation": str(payload["operation"]),
            "project_id": str(payload["project_id"]).strip().lower(),
            "scope": payload["scope"],
        },
        "signature_hex": signature_hex,
    }


def project_registry(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic registry derived from the append-only event store."""
    bootstrap: dict[str, Any] | None = None
    actors: dict[str, dict[str, Any]] = {}
    used_nonces: set[str] = set()
    public_keys: dict[str, str] = {}
    for event in events:
        action = event.get("action")
        payload = event.get("payload") or {}
        auth = payload.get("authorization") or payload.get("_authorization")
        if isinstance(auth, dict):
            nonce = str((auth.get("payload") or {}).get("nonce") or payload.get("nonce") or "").strip().lower()
            if nonce:
                used_nonces.add(nonce)
        if action == "actor.bootstrap":
            bootstrap = {
                "alg": ALG,
                "public_key_hex": str(payload["public_key_hex"]).strip().lower(),
                "fingerprint_sha256": str(payload["fingerprint_sha256"]).strip().lower(),
                "event_seq": event.get("event_seq"),
            }
        elif action == "actor.register":
            actor_id = str(payload["actor_id"])
            public_key_hex = str(payload.get("actor_public_key_hex") or "").strip().lower()
            actors[actor_id] = {
                "actor_id": actor_id,
                "role": _normalize_role(str(payload["role"])),
                "authorization_scope": list(payload.get("authorization_scope") or []),
                "actor_public_key_hex": public_key_hex,
                "event_seq": event.get("event_seq"),
            }
            if public_key_hex:
                public_keys[public_key_hex] = actor_id
    return {
        "active": bootstrap is not None,
        "bootstrap": bootstrap,
        "actors": actors,
        "used_nonces": used_nonces,
        "public_keys": public_keys,
    }


def require_active_registry(events: list[dict[str, Any]]) -> dict[str, Any]:
    registry = project_registry(events)
    if not registry["active"]:
        raise ESAAError("ACTOR_BOOTSTRAP_REQUIRED", "identity contract is not bootstrapped")
    return registry


def assert_anchor_matches_registry(root: Path, registry: dict[str, Any]) -> dict[str, str]:
    anchor = load_anchor(root)
    bootstrap = registry["bootstrap"]
    if (
        anchor["public_key_hex"] != bootstrap["public_key_hex"]
        or anchor["fingerprint_sha256"] != bootstrap["fingerprint_sha256"]
    ):
        raise ESAAError("ANCHOR_MISMATCH", "protected public anchor does not match bootstrapped authority")
    return anchor


def consume_nonce(registry: dict[str, Any], nonce: str) -> None:
    nonce = nonce.strip().lower()
    if nonce in registry["used_nonces"]:
        raise ESAAError("AUTH_REPLAY", "authorization nonce was already consumed")


def reject_orchestrator_impersonation(actor: str) -> None:
    if actor.strip() in RESERVED_ACTOR_IDS:
        raise ESAAError("ORCHESTRATOR_IMPERSONATION", "actor=orchestrator is reserved to the Orchestrator")


def verify_privileged_authorization(
    *,
    root: Path,
    events: list[dict[str, Any]],
    authorization: Any,
    operation: str,
    expected_scope: dict[str, Any],
    signer_public_key_hex: str | None = None,
) -> dict[str, Any]:
    auth = load_authorization(authorization)
    payload = auth["payload"]
    if payload["operation"] != operation:
        raise ESAAError("ACTOR_AUTH_FAILED", f"authorization operation mismatch: {payload['operation']}")
    if payload["alg"] != ALG:
        raise ESAAError("ACTOR_AUTH_FAILED", f"unsupported authorization alg: {payload['alg']}")
    if payload["scope"] != expected_scope:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization scope does not match the requested operation")

    registry = project_registry(events)
    if operation == "actor.bootstrap":
        if registry["active"]:
            raise ESAAError("ACTOR_BOOTSTRAP_EXISTS", "bootstrap authority is already established")
        anchor = load_anchor(root)
        if payload["project_id"] != anchor["fingerprint_sha256"]:
            raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match the public anchor")
        verify_signature(anchor["public_key_hex"], payload, auth["signature_hex"])
        consume_nonce(registry, payload["nonce"])
        return {"anchor": anchor, "registry": registry, "authorization": auth}

    registry = require_active_registry(events)
    anchor = assert_anchor_matches_registry(root, registry)
    if payload["project_id"] != registry["bootstrap"]["fingerprint_sha256"]:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match bootstrapped authority")
    consume_nonce(registry, payload["nonce"])
    key = signer_public_key_hex or registry["bootstrap"]["public_key_hex"]
    verify_signature(key, payload, auth["signature_hex"])
    return {"anchor": anchor, "registry": registry, "authorization": auth}


def prepare_register_scope(
    *,
    actor_id: str,
    role: str,
    authorization_scope: list[str],
    actor_public_key_hex: str,
) -> dict[str, Any]:
    actor_id = actor_id.strip()
    if not actor_id:
        raise ESAAError("INVALID_ARGUMENT", "actor_id is required")
    reject_orchestrator_impersonation(actor_id)
    role = _normalize_role(role)
    if role not in REGISTERABLE_ROLES:
        raise ESAAError("ACTOR_SELF_ELEVATION", f"role {role} cannot be registered")
    public_key_hex = actor_public_key_hex.strip().lower()
    _parse_hex(public_key_hex, "actor_public_key_hex")
    scopes = [item.strip() for item in authorization_scope if item.strip()]
    if not scopes:
        raise ESAAError("INVALID_ARGUMENT", "authorization_scope is required")
    return {
        "actor_id": actor_id,
        "role": role,
        "authorization_scope": scopes,
        "actor_public_key_hex": public_key_hex,
    }


def assert_registerable(registry: dict[str, Any], scope: dict[str, Any]) -> None:
    actor_id = scope["actor_id"]
    public_key_hex = scope["actor_public_key_hex"]
    existing = registry["actors"].get(actor_id)
    if existing:
        if (
            existing["role"] != scope["role"]
            or existing["actor_public_key_hex"] != public_key_hex
            or existing["authorization_scope"] != scope["authorization_scope"]
        ):
            raise ESAAError("ACTOR_DUPLICATE", f"incompatible registration already exists for {actor_id}")
        raise ESAAError("ACTOR_DUPLICATE", f"actor already registered: {actor_id}")
    owner = registry["public_keys"].get(public_key_hex)
    if owner and owner != actor_id:
        raise ESAAError("ACTOR_DUPLICATE", f"public key already bound to actor {owner}")
    if public_key_hex == registry["bootstrap"]["public_key_hex"]:
        raise ESAAError(
            "ACTOR_SELF_ELEVATION",
            "bootstrap public key cannot be reused as a registered actor identity",
        )


def assert_review_identity(
    *,
    registry: dict[str, Any],
    actor: str,
    task: dict[str, Any],
    decision: str,
    authorization: Any,
) -> dict[str, Any]:
    reject_orchestrator_impersonation(actor)
    recorded = registry["actors"].get(actor)
    if recorded is None:
        raise ESAAError("ACTOR_NOT_REGISTERED", f"actor is not registered: {actor}")
    if recorded["role"] not in REVIEW_ROLES:
        raise ESAAError("REVIEW_ROLE_VIOLATION", f"actor {actor} role={recorded['role']} cannot review")
    claimant = str(task.get("assigned_to") or "")
    if actor == claimant:
        raise ESAAError("SELF_REVIEW_FORBIDDEN", "claimant cannot review their own task")
    if "review" not in recorded["authorization_scope"]:
        raise ESAAError("REVIEW_ROLE_VIOLATION", f"actor {actor} is not authorized for review")
    expected_scope = {
        "actor_id": actor,
        "task_id": task["task_id"],
        "decision": decision,
    }
    auth = load_authorization(authorization)
    if auth["payload"]["operation"] != "review":
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization operation must be review")
    if auth["payload"]["scope"] != expected_scope:
        raise ESAAError("ACTOR_AUTH_FAILED", "review authorization scope does not match the request")
    if auth["payload"]["project_id"] != registry["bootstrap"]["fingerprint_sha256"]:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match bootstrapped authority")
    consume_nonce(registry, auth["payload"]["nonce"])
    verify_signature(recorded["actor_public_key_hex"], auth["payload"], auth["signature_hex"])
    return auth


def authorize_review_event(
    *,
    root: Path,
    events: list[dict[str, Any]],
    actor: str,
    task: dict[str, Any],
    decision: str,
    authorization: Any,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Return payload extras for a review event. Dry-run uses the same path."""
    from .runtime_policy import resolve_role, review_authorization_mode

    reject_orchestrator_impersonation(actor)
    registry = project_registry(events)
    if registry["active"]:
        if authorization is None:
            raise ESAAError(
                "ACTOR_AUTH_FAILED",
                "review requires a signed authorization when the identity contract is active",
            )
        assert_anchor_matches_registry(root, registry)
        auth = assert_review_identity(
            registry=registry,
            actor=actor,
            task=task,
            decision=decision,
            authorization=authorization,
        )
        return {
            "_reviewer_role": registry["actors"][actor]["role"],
            "_authorization": auth,
        }

    extras: dict[str, Any] = {}
    mode = review_authorization_mode(policy)
    role = resolve_role(actor, root=root)
    if mode == "qa_role":
        if role not in {"qa", "orchestrator"}:
            raise ESAAError(
                "REVIEW_ROLE_VIOLATION",
                f"actor {actor} role={role} not authorized to review (qa_role mode)",
            )
        extras["_reviewer_role"] = role
    return extras


def _normalize_role(role: str) -> str:
    value = role.strip()
    if value == "quality":
        return "qa"
    return value


def _parse_hex(value: str, field: str) -> bytes:
    text = value.strip().lower()
    if len(text) % 2 != 0 or any(c not in "0123456789abcdef" for c in text):
        raise ESAAError("ACTOR_AUTH_FAILED", f"{field} must be lowercase hex")
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise ESAAError("ACTOR_AUTH_FAILED", f"{field} must be lowercase hex") from exc
    if field in {"public_key_hex", "actor_public_key_hex"} and len(raw) != 32:
        raise ESAAError("ACTOR_AUTH_FAILED", f"{field} must be a 32-byte Ed25519 public key")
    if field == "signature_hex" and len(raw) != 64:
        raise ESAAError("ACTOR_AUTH_FAILED", "signature_hex must be a 64-byte Ed25519 signature")
    return raw
