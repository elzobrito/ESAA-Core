"""Canonical principal identity: owner-bound aliases, signed claim/complete, distinct QA."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.identity import public_key_fingerprint
from esaa.service import ESAAService
from esaa.store import parse_event_store
from test_actor_registration import (
    _activated,
    _alias_auth,
    _bootstrap_auth,
    _copy_runtime,
    _import_owner_pin,
    _key,
    _ready_task,
    _register_auth,
    _review_auth,
    _transition_auth,
    _write_anchor,
)


def _nonce() -> str:
    return os.urandom(16).hex()


def _register(
    svc: ESAAService,
    keys: dict[str, object],
    actor_id: str,
    role: str,
    public_hex: str,
    scope: list[str] | None = None,
) -> None:
    scopes = scope or ["claim"]
    svc.register_actor(
        actor_id=actor_id,
        role=role,
        authorization_scope=scopes,
        actor_public_key_hex=public_hex,
        authorization=_register_auth(
            keys["owner"], keys["project_id"], _nonce(), actor_id, role, public_hex, scopes
        ),
    )


def _bind(svc: ESAAService, keys: dict[str, object], actor_id: str, alias_id: str) -> None:
    svc.bind_actor_alias(
        actor_id=actor_id,
        alias_id=alias_id,
        authorization=_alias_auth(keys["owner"], keys["project_id"], _nonce(), actor_id, alias_id),
    )


def _claim(
    svc: ESAAService,
    keys: dict[str, object],
    actor: str,
    private: Ed25519PrivateKey,
    task_id: str = "T-1000",
) -> dict:
    return svc.submit(
        {"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}},
        actor=actor,
        authorization=_transition_auth(private, keys["project_id"], _nonce(), actor, task_id, "claim"),
    )


def _complete(
    svc: ESAAService,
    keys: dict[str, object],
    actor: str,
    private: Ed25519PrivateKey,
    task_id: str = "T-1000",
) -> dict:
    return svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": task_id,
                "prior_status": "in_progress",
                "verification": {"checks": ["ok"]},
            },
            "file_updates": [{"path": f"docs/spec/{task_id}.md", "content": "ok\n"}],
        },
        actor=actor,
        authorization=_transition_auth(private, keys["project_id"], _nonce(), actor, task_id, "complete"),
    )


def _principal_a(tmp_path: Path, repo_root: Path) -> tuple[ESAAService, dict[str, object], Ed25519PrivateKey, str]:
    svc, keys = _activated(tmp_path, repo_root)
    private, public_hex = _key()
    _register(svc, keys, "actor-a", "implementation", public_hex, ["claim"])
    _bind(svc, keys, "actor-a", "alias-x")
    _bind(svc, keys, "actor-a", "alias-y")
    _bind(svc, keys, "actor-a", "alias-z")
    shown = svc.show_actor_registry()
    assert shown["aliases"] == {"alias-x": "actor-a", "alias-y": "actor-a", "alias-z": "actor-a"}
    return svc, keys, private, public_hex


def test_unsigned_claim_after_activation_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        svc.submit(
            {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
            actor="agent-spec",
        )
    assert exc.value.code == "ACTOR_AUTH_FAILED"


def test_legacy_unsigned_claimant_cannot_be_reviewed_after_activation(
    tmp_path: Path, repo_root: Path
) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _ready_task(svc)
    owner, owner_pub = _key()
    reviewer, reviewer_pub = _key()
    anchor = _write_anchor(tmp_path, owner_pub)
    _import_owner_pin(tmp_path, owner_pub)
    svc.bootstrap_actor_authority(_bootstrap_auth(owner, owner_pub, "aa" * 16))
    svc.register_actor(
        actor_id="reviewer-qa",
        role="qa",
        authorization_scope=["review"],
        actor_public_key_hex=reviewer_pub,
        authorization=_register_auth(
            owner, anchor["fingerprint_sha256"], "bb" * 16, "reviewer-qa", "qa", reviewer_pub
        ),
    )
    auth = _review_auth(reviewer, anchor["fingerprint_sha256"], _nonce(), "reviewer-qa", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert exc.value.code == "PRINCIPAL_UNBOUND"


def test_alias_xyz_of_a_can_complete_and_distinct_qa_accepts(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private, public_hex = _principal_a(tmp_path, repo_root)
    claimed = _claim(svc, keys, "alias-x", private)
    assert claimed["status"] == "accepted"
    completed = _complete(svc, keys, "alias-y", private)
    assert completed["status"] == "accepted"
    events = parse_event_store(tmp_path)
    claim_event = next(event for event in events if event["action"] == "claim")
    complete_event = next(event for event in reversed(events) if event["action"] == "complete")
    principal = public_key_fingerprint(public_hex)
    assert claim_event["payload"]["_principal_id"] == principal
    assert complete_event["payload"]["_principal_id"] == principal
    assert claim_event["payload"]["_alias_id"] == "alias-x"
    assert complete_event["payload"]["_alias_id"] == "alias-y"
    auth = _review_auth(keys["reviewer"], keys["project_id"], _nonce(), "reviewer-qa", "T-1000", "approve")
    result = svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert result["status"] == "accepted"
    assert result["task"]["status"] == "done"
    one = svc.replay(write_views=False)
    two = svc.replay(write_views=False)
    assert one == two
    assert svc.verify()["verify_status"] == "ok"


def test_b_cannot_complete_a_task(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private_a, _pub_a = _principal_a(tmp_path, repo_root)
    private_b, pub_b = _key()
    _register(svc, keys, "actor-b", "implementation", pub_b, ["claim"])
    _claim(svc, keys, "actor-a", private_a)
    with pytest.raises(ESAAError) as exc:
        _complete(svc, keys, "actor-b", private_b)
    assert exc.value.code == "LOCK_VIOLATION"


def test_b_signing_as_a_alias_is_invalid_signature(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private_a, _pub_a = _principal_a(tmp_path, repo_root)
    private_b, _pub_b = _key()
    _claim(svc, keys, "alias-x", private_a)
    with pytest.raises(ESAAError) as exc:
        _complete(svc, keys, "alias-y", private_b)
    assert exc.value.code == "AUTH_SIGNATURE_INVALID"


def test_qa_alias_cannot_self_review(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _bind(svc, keys, "reviewer-qa", "reviewer-alias")
    _claim(svc, keys, "reviewer-alias", keys["reviewer"])
    _complete(svc, keys, "reviewer-alias", keys["reviewer"])
    auth = _review_auth(keys["reviewer"], keys["project_id"], _nonce(), "reviewer-qa", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"


def test_unsigned_qa_alias_claim_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _bind(svc, keys, "reviewer-qa", "reviewer-alias")
    with pytest.raises(ESAAError) as exc:
        svc.submit(
            {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
            actor="reviewer-alias",
        )
    assert exc.value.code == "ACTOR_AUTH_FAILED"


def test_orphan_alias_is_unregistered(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private, _pub = _principal_a(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        _claim(svc, keys, "ghost-alias", private)
    assert exc.value.code == "ACTOR_NOT_REGISTERED"


def test_shared_credential_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, _private, public_hex = _principal_a(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        _register(svc, keys, "actor-shared", "implementation", public_hex, ["claim"])
    assert exc.value.code == "ACTOR_DUPLICATE"


def test_duplicate_alias_and_actor_id_collision_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, _private, _pub = _principal_a(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        _bind(svc, keys, "actor-a", "alias-x")
    assert exc.value.code == "ACTOR_DUPLICATE"
    with pytest.raises(ESAAError) as exc:
        _bind(svc, keys, "actor-a", "reviewer-qa")
    assert exc.value.code == "ACTOR_DUPLICATE"
    with pytest.raises(ESAAError) as exc:
        _bind(svc, keys, "missing-actor", "alias-new")
    assert exc.value.code == "ACTOR_NOT_REGISTERED"


def test_foreign_project_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private, _pub = _principal_a(tmp_path, repo_root)
    auth = _transition_auth(private, "00" * 32, _nonce(), "alias-x", "T-1000", "claim")
    with pytest.raises(ESAAError) as exc:
        svc.submit(
            {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
            actor="alias-x",
            authorization=auth,
        )
    assert exc.value.code == "ACTOR_AUTH_FAILED"


def test_orchestrator_reserved_on_transition_and_alias(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private, _pub = _principal_a(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        _claim(svc, keys, "orchestrator", private)
    assert exc.value.code == "ORCHESTRATOR_IMPERSONATION"
    with pytest.raises(ESAAError) as exc:
        _bind(svc, keys, "actor-a", "orchestrator")
    assert exc.value.code == "ORCHESTRATOR_IMPERSONATION"


def test_invalid_transition_signature_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, _private, _pub = _principal_a(tmp_path, repo_root)
    other, _ = _key()
    with pytest.raises(ESAAError) as exc:
        _claim(svc, keys, "alias-x", other)
    assert exc.value.code == "AUTH_SIGNATURE_INVALID"


def test_transition_nonce_replay_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, private, _pub = _principal_a(tmp_path, repo_root)
    nonce = _nonce()
    auth = _transition_auth(private, keys["project_id"], nonce, "alias-x", "T-1000", "claim")
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="alias-x",
        authorization=auth,
    )
    with pytest.raises(ESAAError) as exc:
        svc.submit(
            {
                "activity_event": {
                    "action": "complete",
                    "task_id": "T-1000",
                    "prior_status": "in_progress",
                    "verification": {"checks": ["ok"]},
                },
                "file_updates": [{"path": "docs/spec/T-1000.md", "content": "ok\n"}],
            },
            actor="alias-x",
            authorization=_transition_auth(private, keys["project_id"], nonce, "alias-x", "T-1000", "complete"),
        )
    assert exc.value.code == "AUTH_REPLAY"


def test_bind_alias_without_bootstrap_rejected(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, _pub = _key()
    with pytest.raises(ESAAError) as exc:
        svc.bind_actor_alias(
            actor_id="agent-spec",
            alias_id="alias-x",
            authorization=_alias_auth(owner, "00" * 32, _nonce(), "agent-spec", "alias-x"),
        )
    assert exc.value.code == "ACTOR_BOOTSTRAP_REQUIRED"


def test_cli_bind_alias_roundtrip(tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESAA_RUNNER_ID", "grok")
    auth_path = tmp_path / "bind-alias.json"
    auth_path.write_text(
        json.dumps(_alias_auth(keys["owner"], keys["project_id"], _nonce(), "agent-spec", "spec-alias")),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "actor",
                "bind-alias",
                "--actor-id",
                "agent-spec",
                "--alias-id",
                "spec-alias",
                "--authorization",
                str(auth_path),
            ]
        )
        == 0
    )
    shown = ESAAService(tmp_path).show_actor_registry()
    assert shown["aliases"]["spec-alias"] == "agent-spec"


def test_historical_bind_alias_tamper_is_corrupted(tmp_path: Path, repo_root: Path) -> None:
    svc, keys, _private, _pub = _principal_a(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    bind = next(event for event in events if event["action"] == "actor.bind_alias")
    bind["payload"]["authorization"]["signature_hex"] = "00" * 64
    (tmp_path / ".roadmap" / "activity.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    assert svc.verify()["verify_status"] == "corrupted"
    assert svc.verify()["error_code"] == "AUTH_SIGNATURE_INVALID"
