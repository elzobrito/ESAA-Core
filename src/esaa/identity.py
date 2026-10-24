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
IDENTITY_EPOCH = "esaa.identity.v1"
ANCHOR_REL = ".roadmap/governance-anchor.json"
RESERVED_ACTOR_IDS = frozenset({"orchestrator"})
REGISTERABLE_ROLES = frozenset({"qa", "specification", "implementation"})
REVIEW_ROLES = frozenset({"qa"})
PRIVILEGED_OPERATIONS = frozenset(
    {"actor.bootstrap", "actor.register", "actor.bind_alias", "review", "claim", "complete"}
)
REGISTRY_OPERATIONS = frozenset({"actor.bootstrap", "actor.register", "actor.bind_alias"})
TRANSITION_OPERATIONS = frozenset({"claim", "complete"})


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
    aliases: dict[str, str] = {}
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
        elif action == "actor.bind_alias":
            aliases[str(payload["alias_id"])] = str(payload["actor_id"])
    return {
        "active": bootstrap is not None,
        "bootstrap": bootstrap,
        "actors": actors,
        "aliases": aliases,
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
        from .trust_root import require_pin_for_activation
        pin = require_pin_for_activation(root)
        anchor = load_anchor(root)
        if payload["project_id"] != pin["fingerprint_sha256"]:
            raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match the external pin")
        if payload["project_id"] != anchor["fingerprint_sha256"]:
            raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match the public anchor")
        verify_signature(pin["public_key_hex"], payload, auth["signature_hex"])
        consume_nonce(registry, payload["nonce"])
        return {"anchor": anchor, "registry": registry, "authorization": auth, "trust_pin": pin}

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


def resolve_principal(registry: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """Map a presented actor/alias string to the owner-bound canonical principal."""
    actor_id = actor_id.strip()
    reject_orchestrator_impersonation(actor_id)
    if not actor_id:
        raise ESAAError("PRINCIPAL_UNBOUND", "actor_id is required")
    recorded = registry["actors"].get(actor_id)
    alias_id = actor_id
    if recorded is None:
        principal_actor = registry.get("aliases", {}).get(actor_id)
        if not principal_actor:
            raise ESAAError("ACTOR_NOT_REGISTERED", f"actor is not registered: {actor_id}")
        recorded = registry["actors"].get(principal_actor)
        if recorded is None:
            raise ESAAError("PRINCIPAL_UNBOUND", f"alias {actor_id} is bound to an unknown principal")
        actor_id = principal_actor
    public_key_hex = recorded["actor_public_key_hex"]
    return {
        "actor_id": recorded["actor_id"],
        "alias_id": alias_id,
        "principal_id": public_key_fingerprint(public_key_hex),
        "role": recorded["role"],
        "actor_public_key_hex": public_key_hex,
        "authorization_scope": list(recorded["authorization_scope"]),
    }


def prepare_alias_scope(*, actor_id: str, alias_id: str) -> dict[str, str]:
    actor_id = actor_id.strip()
    alias_id = alias_id.strip()
    if not actor_id or not alias_id:
        raise ESAAError("INVALID_ARGUMENT", "actor_id and alias_id are required")
    reject_orchestrator_impersonation(actor_id)
    reject_orchestrator_impersonation(alias_id)
    if actor_id == alias_id:
        raise ESAAError("INVALID_ARGUMENT", "alias_id must differ from actor_id")
    return {"actor_id": actor_id, "alias_id": alias_id}


def assert_bindable(registry: dict[str, Any], scope: dict[str, str]) -> None:
    actor_id = scope["actor_id"]
    alias_id = scope["alias_id"]
    if actor_id not in registry["actors"]:
        raise ESAAError("ACTOR_NOT_REGISTERED", f"actor is not registered: {actor_id}")
    if alias_id in registry["actors"]:
        raise ESAAError("ACTOR_DUPLICATE", f"alias collides with registered actor {alias_id}")
    existing = registry.get("aliases", {}).get(alias_id)
    if existing:
        raise ESAAError("ACTOR_DUPLICATE", f"alias already bound: {alias_id}")


def last_transition_principal(events: list[dict[str, Any]], action: str, task_id: str) -> str | None:
    found: str | None = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("action") == action and payload.get("task_id") == task_id:
            principal = payload.get("_principal_id")
            found = str(principal) if principal else None
    return found


def authorize_actor_transition(
    *,
    registry: dict[str, Any],
    actor: str,
    operation: str,
    task_id: str,
    authorization: Any,
) -> dict[str, Any]:
    if operation not in TRANSITION_OPERATIONS:
        raise ESAAError("ACTOR_AUTH_FAILED", f"unsupported transition operation: {operation}")
    if authorization is None:
        raise ESAAError(
            "ACTOR_AUTH_FAILED",
            f"{operation} requires a signed authorization when the identity contract is active",
        )
    principal = resolve_principal(registry, actor)
    expected_scope = {"actor_id": actor, "task_id": task_id}
    auth = load_authorization(authorization)
    if auth["payload"]["operation"] != operation:
        raise ESAAError("ACTOR_AUTH_FAILED", f"authorization operation mismatch: {auth['payload']['operation']}")
    if auth["payload"]["scope"] != expected_scope:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization scope does not match the requested operation")
    if auth["payload"]["project_id"] != registry["bootstrap"]["fingerprint_sha256"]:
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization project_id does not match bootstrapped authority")
    consume_nonce(registry, auth["payload"]["nonce"])
    verify_signature(principal["actor_public_key_hex"], auth["payload"], auth["signature_hex"])
    return {
        "identity_epoch": IDENTITY_EPOCH,
        "_principal_id": principal["principal_id"],
        "_alias_id": principal["alias_id"],
        "_authorization": auth,
    }


def assert_review_identity(
    *,
    registry: dict[str, Any],
    actor: str,
    task: dict[str, Any],
    decision: str,
    authorization: Any,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reject_orchestrator_impersonation(actor)
    principal = resolve_principal(registry, actor)
    if principal["role"] not in REVIEW_ROLES:
        raise ESAAError("REVIEW_ROLE_VIOLATION", f"actor {actor} role={principal['role']} cannot review")
    claimant = str(task.get("assigned_to") or "")
    if actor == claimant or principal["actor_id"] == claimant:
        raise ESAAError("SELF_REVIEW_FORBIDDEN", "claimant cannot review their own task")
    if "review" not in principal["authorization_scope"]:
        raise ESAAError("REVIEW_ROLE_VIOLATION", f"actor {actor} is not authorized for review")
    task_id = task["task_id"]
    history = events or []
    claimant_principal = last_transition_principal(history, "claim", task_id)
    completer_principal = last_transition_principal(history, "complete", task_id)
    if claimant_principal is None or completer_principal is None:
        raise ESAAError("PRINCIPAL_UNBOUND", "review requires a canonical claimant and completer principal")
    if principal["principal_id"] in {claimant_principal, completer_principal}:
        raise ESAAError("SELF_REVIEW_FORBIDDEN", "reviewer principal is not distinct from claimant/completer")
    expected_scope = {
        "actor_id": actor,
        "task_id": task_id,
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
    verify_signature(principal["actor_public_key_hex"], auth["payload"], auth["signature_hex"])
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
            events=events,
        )
        principal = resolve_principal(registry, actor)
        return {
            "identity_epoch": IDENTITY_EPOCH,
            "_principal_id": principal["principal_id"],
            "_alias_id": principal["alias_id"],
            "_reviewer_role": principal["role"],
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


def authorize_agent_event(
    *,
    root: Path,
    events: list[dict[str, Any]],
    actor: str,
    task: dict[str, Any],
    action: str,
    decision: str,
    authorization: Any,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if action == "review":
        return authorize_review_event(
            root=root,
            events=events,
            actor=actor,
            task=task,
            decision=decision,
            authorization=authorization,
            policy=policy,
        )
    if action in TRANSITION_OPERATIONS:
        registry = project_registry(events)
        if not registry["active"]:
            return {}
        assert_anchor_matches_registry(root, registry)
        extras = authorize_actor_transition(
            registry=registry,
            actor=actor,
            operation=action,
            task_id=str(task["task_id"]),
            authorization=authorization,
        )
        if action == "complete":
            claimant_principal = last_transition_principal(events, "claim", str(task["task_id"]))
            if claimant_principal is None:
                raise ESAAError("PRINCIPAL_UNBOUND", "complete requires a canonical claimant principal")
            if extras["_principal_id"] != claimant_principal:
                raise ESAAError("LOCK_VIOLATION", "completer principal does not match claimant principal")
        return extras
    return {}


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
