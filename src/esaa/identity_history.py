"""Chronological identity v1 validation, shared by readers and appenders.

Legacy unsigned events remain legacy only before the first bootstrap. The
current public anchor is required for authenticated history; external trust
and anti-rollback enrollment are deliberately owned by hotfix 002.
"""
from pathlib import Path
from typing import Any, cast

from .errors import CorruptedStoreError, ESAAError
from .identity import (
    ALG, assert_registerable, assert_review_identity, load_authorization, load_anchor,
    prepare_register_scope, project_registry, verify_privileged_authorization,
)

EPOCH = "esaa.identity.v1"


def validate_identity_representation(raw: dict[str, Any]) -> None:
    """Do not let legacy normalization discard a supplied signed envelope."""
    if not isinstance(raw, dict):
        raise CorruptedStoreError("JSONL_INVALID", "event must be a JSON object")
    reserved = {"authorization", "_authorization", "identity_epoch"}
    if reserved.intersection(raw):
        raise CorruptedStoreError("ACTOR_AUTH_FAILED", "authorization metadata must be inside event payload")
    data = raw.get("data")
    if "payload" in raw and isinstance(data, dict) and reserved.intersection(data):
        raise CorruptedStoreError("ACTOR_AUTH_FAILED", "ambiguous payload/data identity representation")
    payload = raw.get("payload", data)
    signed = isinstance(payload, dict) and bool(reserved.intersection(payload))
    version = raw.get("schema_version", "0.3.0")
    if (signed or raw.get("action") in {"actor.bootstrap", "actor.register"}) and (not isinstance(version, str) or version not in {"0.3.0", "0.4.0", "0.4.1", "0.4.2"}):
        raise CorruptedStoreError("AUTH_EPOCH_UNSUPPORTED", "unsupported signed event schema")


def validate_identity_history(root: Path, events: list[dict[str, Any]]) -> None:
    """Authenticate each operation against the previously validated prefix."""
    prefix: list[dict[str, Any]] = []
    claimants: dict[str, str] = {}
    active = False
    for event in events:
        try:
            validate_identity_representation(event)
            action = event["action"]
            payload = event["payload"]
            if not isinstance(payload, dict):
                raise ESAAError("ACTOR_AUTH_FAILED", "event payload must be an object")
            epoch = payload.get("identity_epoch", EPOCH)
            if epoch != EPOCH:
                raise ESAAError("AUTH_EPOCH_UNSUPPORTED", "unsupported identity epoch")
            present = "authorization" in payload or "_authorization" in payload
            if "authorization" in payload and "_authorization" in payload:
                raise ESAAError("ACTOR_AUTH_FAILED", "ambiguous authorization representation")
            if action in {"actor.bootstrap", "actor.register"}:
                if event["actor"] != "orchestrator":
                    raise ESAAError("ORCHESTRATOR_IMPERSONATION", "registry events require Orchestrator provenance")
                if action == "actor.bootstrap":
                    if payload.get("alg") != ALG:
                        raise ESAAError("ACTOR_AUTH_FAILED", "unsupported bootstrap algorithm")
                    scope = {"public_key_hex": payload.get("public_key_hex"),
                             "fingerprint_sha256": payload.get("fingerprint_sha256")}
                    anchor = load_anchor(root)
                    if scope != {"public_key_hex": anchor["public_key_hex"],
                                 "fingerprint_sha256": anchor["fingerprint_sha256"]}:
                        raise ESAAError("ANCHOR_MISMATCH", "historical bootstrap disagrees with contextual anchor")
                else:
                    scope = prepare_register_scope(actor_id=payload.get("actor_id", ""),
                        role=payload.get("role", ""),
                        authorization_scope=payload.get("authorization_scope", []),
                        actor_public_key_hex=payload.get("actor_public_key_hex", ""))
                checked = verify_privileged_authorization(root=root, events=prefix,
                    authorization=payload.get("authorization"), operation=action, expected_scope=scope)
                if action == "actor.register":
                    assert_registerable(checked["registry"], scope)
                active = True
            elif action == "review" and (active or present):
                registry = project_registry(prefix)
                if not registry["active"]:
                    raise ESAAError("ACTOR_BOOTSTRAP_REQUIRED", "signed review lacks prior authority")
                from .identity import assert_anchor_matches_registry
                assert_anchor_matches_registry(root, registry)
                actor = event["actor"]
                auth = load_authorization(payload.get("_authorization"))
                task_id = cast(str, payload.get("task_id"))
                if payload.get("tasks", [task_id]) != [task_id]:
                    raise ESAAError("ACTOR_AUTH_FAILED", "signed review must cover exactly its task")
                assert_review_identity(registry=registry, actor=actor,
                    task={"task_id": task_id, "assigned_to": claimants.get(task_id, "")},
                    decision=cast(str, payload.get("decision")), authorization=auth)
                role = event.get("reviewer_role", payload.get("_reviewer_role"))
                if role != registry["actors"][actor]["role"]:
                    raise ESAAError("REVIEW_ROLE_VIOLATION", "historical reviewer role disagrees with registry")
            elif present:
                # Never discard a supplied invalid/unknown signed envelope as legacy.
                raise ESAAError("ACTOR_AUTH_FAILED", "unexpected signed event operation")
            if action == "claim":
                claimants[cast(str, payload.get("task_id"))] = event["actor"]
            prefix.append(event)
        except ESAAError as exc:
            raise CorruptedStoreError(exc.code, f"identity at event_seq={event.get('event_seq')}: {exc.message}") from exc
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise CorruptedStoreError("ACTOR_AUTH_FAILED", f"invalid identity data at event_seq={event.get('event_seq')}") from exc
