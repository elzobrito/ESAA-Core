"""Orchestrator-mediated actor bootstrap and registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import ESAAError
from .events import make_event
from .identity import (
    ALG,
    assert_anchor_matches_registry,
    assert_bindable,
    assert_registerable,
    load_anchor,
    prepare_alias_scope,
    prepare_register_scope,
    project_registry,
    verify_privileged_authorization,
)
from .store import next_event_seq, parse_event_store
from .trust_root import import_trust_pin, require_pin_for_activation

if TYPE_CHECKING:
    from pathlib import Path


class ActorAdminMixin:
    if TYPE_CHECKING:
        root: Path

        def _commit_orchestrator_events(
            self, candidate_events: list[dict[str, Any]], dry_run: bool = False,
            precommit: Any = None, postcommit: Any = None
        ) -> dict[str, Any]: ...

    def bootstrap_actor_authority(
        self,
        authorization: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        events = parse_event_store(self.root)
        require_pin_for_activation(self.root)
        anchor = load_anchor(self.root)
        expected_scope = {
            "public_key_hex": anchor["public_key_hex"],
            "fingerprint_sha256": anchor["fingerprint_sha256"],
        }
        verified = verify_privileged_authorization(
            root=self.root,
            events=events,
            authorization=authorization,
            operation="actor.bootstrap",
            expected_scope=expected_scope,
            signer_public_key_hex=anchor["public_key_hex"],
        )
        payload = {
            "alg": ALG,
            "public_key_hex": anchor["public_key_hex"],
            "fingerprint_sha256": anchor["fingerprint_sha256"],
            "authorization": verified["authorization"],
        }
        event = make_event(
            next_event_seq(events), actor="orchestrator", action="actor.bootstrap", payload=payload
        )
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result["identity_contract"] = "active"
        result["fingerprint_sha256"] = anchor["fingerprint_sha256"]
        return result

    def register_actor(
        self,
        *,
        actor_id: str,
        role: str,
        authorization_scope: list[str],
        actor_public_key_hex: str,
        authorization: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        events = parse_event_store(self.root)
        registry = project_registry(events)
        if not registry["active"]:
            raise ESAAError("ACTOR_BOOTSTRAP_REQUIRED", "identity contract is not bootstrapped")
        assert_anchor_matches_registry(self.root, registry)
        scope = prepare_register_scope(
            actor_id=actor_id,
            role=role,
            authorization_scope=authorization_scope,
            actor_public_key_hex=actor_public_key_hex,
        )
        verified = verify_privileged_authorization(
            root=self.root,
            events=events,
            authorization=authorization,
            operation="actor.register",
            expected_scope=scope,
            signer_public_key_hex=registry["bootstrap"]["public_key_hex"],
        )
        assert_registerable(verified["registry"], scope)
        payload = {
            **scope,
            "authorization": verified["authorization"],
        }
        event = make_event(
            next_event_seq(events), actor="orchestrator", action="actor.register", payload=payload
        )
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result["actor_id"] = scope["actor_id"]
        result["role"] = scope["role"]
        return result

    def bind_actor_alias(
        self,
        *,
        actor_id: str,
        alias_id: str,
        authorization: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        events = parse_event_store(self.root)
        registry = project_registry(events)
        if not registry["active"]:
            raise ESAAError("ACTOR_BOOTSTRAP_REQUIRED", "identity contract is not bootstrapped")
        assert_anchor_matches_registry(self.root, registry)
        scope = prepare_alias_scope(actor_id=actor_id, alias_id=alias_id)
        verified = verify_privileged_authorization(
            root=self.root,
            events=events,
            authorization=authorization,
            operation="actor.bind_alias",
            expected_scope=scope,
            signer_public_key_hex=registry["bootstrap"]["public_key_hex"],
        )
        assert_bindable(verified["registry"], scope)
        payload = {
            **scope,
            "authorization": verified["authorization"],
        }
        event = make_event(
            next_event_seq(events), actor="orchestrator", action="actor.bind_alias", payload=payload
        )
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result["actor_id"] = scope["actor_id"]
        result["alias_id"] = scope["alias_id"]
        return result

    def import_owner_trust_pin(self, pin: dict[str, Any]) -> dict[str, Any]:
        record = import_trust_pin(self.root, pin)
        return {
            "status": "imported",
            "fingerprint_sha256": record["fingerprint_sha256"],
            "project_id": record["project_id"],
            "path": "ESAA_TRUST_ROOT",
        }

    def show_actor_registry(self) -> dict[str, Any]:
        events = parse_event_store(self.root)
        registry = project_registry(events)
        return {
            "identity_contract": "active" if registry["active"] else "inactive",
            "bootstrap": registry["bootstrap"],
            "actors": sorted(registry["actors"].values(), key=lambda item: item["actor_id"]),
            "aliases": dict(sorted(registry.get("aliases", {}).items())),
            "used_nonce_count": len(registry["used_nonces"]),
        }
