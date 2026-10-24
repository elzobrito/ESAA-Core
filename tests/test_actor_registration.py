"""Authenticated actor registry: bootstrap, register, review, negative cases."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.identity import ALG, canonical_authorization_payload, public_key_fingerprint
from esaa.service import ESAAService
from esaa.store import parse_event_store
from esaa.utils import canonical_json_bytes


def _copy_runtime(root: Path, repo_root: Path) -> None:
    roadmap = root / ".roadmap"
    roadmap.mkdir(parents=True, exist_ok=True)
    for name in (
        "AGENT_CONTRACT.yaml",
        "ORCHESTRATOR_CONTRACT.yaml",
        "agent_result.schema.json",
        "roadmap.schema.json",
        "issues.schema.json",
        "lessons.schema.json",
        "RUNTIME_POLICY.yaml",
        "agents_swarm.yaml",
    ):
        source = repo_root / ".roadmap" / name
        if source.exists():
            shutil.copy2(source, roadmap / name)


def _key() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes_raw().hex()
    return private, public_hex


def _sign(private: Ed25519PrivateKey, payload: dict) -> dict:
    signature_hex = private.sign(canonical_json_bytes(payload)).hex()
    return {"payload": payload, "signature_hex": signature_hex}


def _write_anchor(root: Path, public_hex: str) -> dict[str, str]:
    fingerprint = public_key_fingerprint(public_hex)
    payload = {
        "schema_version": "esaa.identity.anchor.v1",
        "alg": ALG,
        "public_key_hex": public_hex,
        "fingerprint_sha256": fingerprint,
    }
    path = root / ".roadmap" / "governance-anchor.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _bootstrap_auth(owner: Ed25519PrivateKey, public_hex: str, nonce: str) -> dict:
    fingerprint = public_key_fingerprint(public_hex)
    payload = canonical_authorization_payload(
        operation="actor.bootstrap",
        project_id=fingerprint,
        nonce=nonce,
        scope={"public_key_hex": public_hex, "fingerprint_sha256": fingerprint},
    )
    return _sign(owner, payload)


def _register_auth(
    owner: Ed25519PrivateKey,
    project_id: str,
    nonce: str,
    actor_id: str,
    role: str,
    actor_public_hex: str,
    scope: list[str] | None = None,
) -> dict:
    payload = canonical_authorization_payload(
        operation="actor.register",
        project_id=project_id,
        nonce=nonce,
        scope={
            "actor_id": actor_id,
            "role": role,
            "authorization_scope": scope or ["review"],
            "actor_public_key_hex": actor_public_hex,
        },
    )
    return _sign(owner, payload)


def _review_auth(
    actor_key: Ed25519PrivateKey,
    project_id: str,
    nonce: str,
    actor_id: str,
    task_id: str,
    decision: str,
) -> dict:
    payload = canonical_authorization_payload(
        operation="review",
        project_id=project_id,
        nonce=nonce,
        scope={"actor_id": actor_id, "task_id": task_id, "decision": decision},
    )
    return _sign(actor_key, payload)


def _ready_task(svc: ESAAService, actor: str = "agent-spec") -> None:
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor=actor,
    )
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
        actor=actor,
    )


def _activated(tmp_path: Path, repo_root: Path) -> tuple[ESAAService, dict[str, object]]:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    reviewer, reviewer_pub = _key()
    anchor = _write_anchor(tmp_path, owner_pub)
    svc.bootstrap_actor_authority(_bootstrap_auth(owner, owner_pub, "aa" * 16))
    svc.register_actor(
        actor_id="reviewer-qa",
        role="qa",
        authorization_scope=["review"],
        actor_public_key_hex=reviewer_pub,
        authorization=_register_auth(owner, anchor["fingerprint_sha256"], "bb" * 16, "reviewer-qa", "qa", reviewer_pub),
    )
    return svc, {
        "owner": owner,
        "owner_pub": owner_pub,
        "reviewer": reviewer,
        "reviewer_pub": reviewer_pub,
        "project_id": anchor["fingerprint_sha256"],
    }


def test_history_without_bootstrap_keeps_qa_role_review(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _ready_task(svc)
    result = svc.review_task("T-1000", actor="agent-qa", decision="approve")
    assert result["status"] == "accepted"
    assert result["task"]["status"] == "done"


def test_bootstrap_and_independent_review(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    auth = _review_auth(
        keys["reviewer"], keys["project_id"], "cc" * 16, "reviewer-qa", "T-1000", "approve"
    )
    result = svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert result["status"] == "accepted"
    assert result["task"]["status"] == "done"
    events = parse_event_store(tmp_path)
    assert any(event["action"] == "actor.bootstrap" for event in events)
    assert any(event["action"] == "actor.register" for event in events)
    replayed = ESAAService(tmp_path).show_actor_registry()
    assert replayed["identity_contract"] == "active"
    assert replayed["actors"][0]["actor_id"] == "reviewer-qa"


def test_unregistered_actor_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    unknown, _ = _key()
    auth = _review_auth(unknown, keys["project_id"], "dd" * 16, "agent-qa-unregistered", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="agent-qa-unregistered", decision="approve", authorization=auth)
    assert exc.value.code == "ACTOR_NOT_REGISTERED"


def test_invalid_signature_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    other, _ = _key()
    auth = _review_auth(other, keys["project_id"], "ee" * 16, "reviewer-qa", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert exc.value.code == "AUTH_SIGNATURE_INVALID"


def test_authorization_replay_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    auth = _review_auth(
        keys["reviewer"], keys["project_id"], "ff" * 16, "reviewer-qa", "T-1000", "request_changes"
    )
    first = svc.review_task("T-1000", actor="reviewer-qa", decision="request_changes", authorization=auth)
    assert first["status"] == "accepted"
    svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": "T-1000",
                "prior_status": "in_progress",
                "verification": {"checks": ["ok-again"]},
            },
            "file_updates": [{"path": "docs/spec/T-1000.md", "content": "ok2\n"}],
        },
        actor="agent-spec",
    )
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="request_changes", authorization=auth)
    assert exc.value.code == "AUTH_REPLAY"


def test_anchor_substitution_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    attacker, attacker_pub = _key()
    _write_anchor(tmp_path, attacker_pub)
    auth = _review_auth(
        keys["reviewer"], keys["project_id"], "11" * 16, "reviewer-qa", "T-1000", "approve"
    )
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth)
    assert exc.value.code == "ANCHOR_MISMATCH"
    _ = attacker


def test_self_review_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    owner = keys["owner"]
    claimant_key, claimant_pub = _key()
    svc.register_actor(
        actor_id="agent-impl",
        role="implementation",
        authorization_scope=["review"],
        actor_public_key_hex=claimant_pub,
        authorization=_register_auth(
            owner, keys["project_id"], "22" * 16, "agent-impl", "implementation", claimant_pub, ["review"]
        ),
    )
    _ready_task(svc, actor="agent-impl")
    auth = _review_auth(claimant_key, keys["project_id"], "33" * 16, "agent-impl", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="agent-impl", decision="approve", authorization=auth)
    assert exc.value.code in {"SELF_REVIEW_FORBIDDEN", "REVIEW_ROLE_VIOLATION"}


def test_claimant_qa_cannot_self_approve(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    owner = keys["owner"]
    qa_key, qa_pub = _key()
    svc.register_actor(
        actor_id="agent-qa",
        role="qa",
        authorization_scope=["review"],
        actor_public_key_hex=qa_pub,
        authorization=_register_auth(owner, keys["project_id"], "44" * 16, "agent-qa", "qa", qa_pub),
    )
    _ready_task(svc, actor="agent-qa")
    auth = _review_auth(qa_key, keys["project_id"], "55" * 16, "agent-qa", "T-1000", "approve")
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="agent-qa", decision="approve", authorization=auth)
    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"


def test_orchestrator_impersonation_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    auth = _review_auth(
        keys["reviewer"], keys["project_id"], "66" * 16, "orchestrator", "T-1000", "approve"
    )
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="orchestrator", decision="approve", authorization=auth)
    assert exc.value.code == "ORCHESTRATOR_IMPERSONATION"


def test_duplicate_public_key_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        svc.register_actor(
            actor_id="reviewer-qa-alias",
            role="qa",
            authorization_scope=["review"],
            actor_public_key_hex=keys["reviewer_pub"],
            authorization=_register_auth(
                keys["owner"],
                keys["project_id"],
                "77" * 16,
                "reviewer-qa-alias",
                "qa",
                keys["reviewer_pub"],
            ),
        )
    assert exc.value.code == "ACTOR_DUPLICATE"


def test_bootstrap_key_cannot_be_registered_as_actor(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        svc.register_actor(
            actor_id="owner-as-qa",
            role="qa",
            authorization_scope=["review"],
            actor_public_key_hex=keys["owner_pub"],
            authorization=_register_auth(
                keys["owner"], keys["project_id"], "88" * 16, "owner-as-qa", "qa", keys["owner_pub"]
            ),
        )
    assert exc.value.code == "ACTOR_SELF_ELEVATION"


def test_second_bootstrap_rejected(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    with pytest.raises(ESAAError) as exc:
        svc.bootstrap_actor_authority(_bootstrap_auth(keys["owner"], keys["owner_pub"], "99" * 16))
    assert exc.value.code == "ACTOR_BOOTSTRAP_EXISTS"


def test_dry_run_review_validates_identity(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc)
    before = len(parse_event_store(tmp_path))
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", dry_run=True)
    assert exc.value.code == "ACTOR_AUTH_FAILED"
    auth = _review_auth(
        keys["reviewer"], keys["project_id"], "ab" * 16, "reviewer-qa", "T-1000", "approve"
    )
    result = svc.review_task(
        "T-1000", actor="reviewer-qa", decision="approve", authorization=auth, dry_run=True
    )
    assert result["status"] == "dry_run"
    assert len(parse_event_store(tmp_path)) == before


def test_cli_actor_register_exists_and_bootstrap_roundtrip(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    _copy_runtime(tmp_path, repo_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESAA_RUNNER_ID", "grok")
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    reviewer, reviewer_pub = _key()
    anchor = _write_anchor(tmp_path, owner_pub)
    bootstrap_path = tmp_path / "bootstrap.json"
    bootstrap_path.write_text(json.dumps(_bootstrap_auth(owner, owner_pub, "ac" * 16)), encoding="utf-8")
    assert main(["--root", str(tmp_path), "actor", "bootstrap", "--authorization", str(bootstrap_path)]) == 0
    register_path = tmp_path / "register.json"
    register_path.write_text(
        json.dumps(
            _register_auth(owner, anchor["fingerprint_sha256"], "ad" * 16, "reviewer-qa", "qa", reviewer_pub)
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "actor",
                "register",
                "--actor-id",
                "reviewer-qa",
                "--role",
                "qa",
                "--scope",
                "review",
                "--actor-public-key",
                reviewer_pub,
                "--authorization",
                str(register_path),
            ]
        )
        == 0
    )
    _ = reviewer
    shown = ESAAService(tmp_path).show_actor_registry()
    assert shown["identity_contract"] == "active"
    assert shown["actors"][0]["actor_id"] == "reviewer-qa"


def test_register_without_bootstrap_rejected(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, _owner_pub = _key()
    _reviewer, reviewer_pub = _key()
    anchor = _write_anchor(tmp_path, _owner_pub)
    with pytest.raises(ESAAError) as exc:
        svc.register_actor(
            actor_id="reviewer-qa",
            role="qa",
            authorization_scope=["review"],
            actor_public_key_hex=reviewer_pub,
            authorization=_register_auth(
                owner, anchor["fingerprint_sha256"], "ae" * 16, "reviewer-qa", "qa", reviewer_pub
            ),
        )
    assert exc.value.code == "ACTOR_BOOTSTRAP_REQUIRED"


def test_cli_unknown_actor_command_was_replaced() -> None:
    with pytest.raises(SystemExit):
        main(["actor", "not-a-command"])
