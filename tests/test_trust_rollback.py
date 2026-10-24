"""External trust pin, monotonic checkpoint, and anti-rollback (hotfix 002)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from esaa.cli import main
from esaa.errors import CorruptedStoreError, ESAAError
from esaa.identity import public_key_fingerprint
from esaa.service import ESAAService
from esaa.store import compute_event_hash, init_hash_chain, parse_event_store
from esaa.trust_root import (
    ENV_TRUST_ROOT,
    bound_record_path,
    make_pin,
    try_load_record,
)
from test_actor_registration import (
    _activated,
    _bind_trust_root,
    _bootstrap_auth,
    _copy_runtime,
    _import_owner_pin,
    _key,
    _ready_task,
    _review_auth,
    _write_anchor,
)


def _write_events(root: Path, events: list[dict]) -> None:
    (root / ".roadmap" / "activity.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _recompute_chain(events: list[dict]) -> list[dict]:
    anchor = next((event for event in events if event["action"] == "chain.anchor"), None)
    if anchor is None:
        return events
    through = int(anchor["payload"]["anchored_through_seq"])
    raw = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events[:through])
    anchor["payload"]["anchor_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prev = anchor["payload"]["anchor_sha256"]
    for event in events[anchor["event_seq"] :]:
        event["prev_event_hash"] = prev
        event["event_hash"] = compute_event_hash(event)
        prev = event["event_hash"]
    return events


def _pin_path(root: Path) -> Path:
    return bound_record_path(root)


def _rewrite_pin(root: Path, mutate) -> dict:
    record = try_load_record(root)
    assert record is not None
    mutate(record)
    path = _pin_path(root)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def test_inactive_workspace_without_pin_keeps_qa_role(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _ready_task(svc)
    result = svc.review_task("T-1000", actor="agent-qa", decision="approve")
    assert result["status"] == "accepted"
    assert svc.verify()["verify_status"] == "ok"


def test_bootstrap_without_pin_is_blocked_environment(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    _write_anchor(tmp_path, owner_pub)
    with pytest.raises(ESAAError) as exc:
        svc.bootstrap_actor_authority(_bootstrap_auth(owner, owner_pub, "aa" * 16))
    assert exc.value.code == "BLOCKED_ENVIRONMENT"


def test_anchor_bytes_are_never_autoenrolled(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    _write_anchor(tmp_path, owner_pub)
    trust = _bind_trust_root(tmp_path)
    with pytest.raises(ESAAError) as exc:
        svc.bootstrap_actor_authority(_bootstrap_auth(owner, owner_pub, "aa" * 16))
    assert exc.value.code == "BLOCKED_ENVIRONMENT"
    assert list(trust.glob("*.json")) == []
    assert not (tmp_path / ".roadmap" / "esaa.identity.trust.v1.json").exists()


def test_trust_root_inside_project_is_blocked(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    _write_anchor(tmp_path, owner_pub)
    inside = tmp_path / ".trust"
    inside.mkdir()
    import os

    os.environ[ENV_TRUST_ROOT] = str(inside)
    with pytest.raises(ESAAError) as exc:
        svc.import_owner_trust_pin(make_pin(public_key_hex=owner_pub))
    assert exc.value.code == "BLOCKED_ENVIRONMENT"


def test_owner_import_then_bootstrap(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    record = try_load_record(tmp_path)
    assert record is not None
    assert record["project_id"] == keys["project_id"]
    assert record["checkpoint"]["bootstrap_event_seq"] is not None
    assert record["checkpoint"]["event_seq"] >= record["checkpoint"]["bootstrap_event_seq"]
    assert svc.verify()["verify_status"] == "ok"


def test_joint_swap_of_anchor_and_bootstrap_is_trust_mismatch(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    init_hash_chain(tmp_path)
    events = parse_event_store(tmp_path)
    attacker, attacker_pub = _key()
    swapped = _write_anchor(tmp_path, attacker_pub)
    for event in events:
        if event["action"] == "actor.bootstrap":
            event["payload"]["public_key_hex"] = attacker_pub
            event["payload"]["fingerprint_sha256"] = swapped["fingerprint_sha256"]
    _write_events(tmp_path, _recompute_chain(events))
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_MISMATCH"
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(tmp_path)
    assert exc.value.code == "TRUST_MISMATCH"
    with pytest.raises(CorruptedStoreError):
        svc.replay(write_views=False)


def test_prebootstrap_rollback_is_trust_rollback(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=_keys)
    events = []
    for event in parse_event_store(tmp_path):
        if event["action"] in {"actor.bootstrap", "actor.register", "actor.bind_alias"}:
            continue
        payload = event.get("payload") or {}
        if payload.get("authorization") or payload.get("_authorization"):
            continue
        events.append(event)
    for seq, event in enumerate(events, 1):
        event["event_seq"] = seq
        event["event_id"] = f"EV-{seq:08d}"
        event.pop("event_hash", None)
        event.pop("prev_event_hash", None)
    _write_events(tmp_path, events)
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_ROLLBACK"
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="agent-qa", decision="approve")
    assert exc.value.code == "TRUST_ROLLBACK"


def test_seq_behind_checkpoint_is_trust_rollback(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    last_seq = parse_event_store(tmp_path)[-1]["event_seq"]
    _rewrite_pin(tmp_path, lambda record: record["checkpoint"].__setitem__("event_seq", last_seq + 25))
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_ROLLBACK"


def test_hash_divergence_at_same_seq_is_trust_mismatch(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    claim = next(event for event in events if event["action"] == "task.create")
    claim["payload"]["title"] = "tampered-title"
    _write_events(tmp_path, events)
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_MISMATCH"


def test_project_id_divergence_is_trust_mismatch(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    _rewrite_pin(
        tmp_path,
        lambda record: (
            record.__setitem__("project_id", "00" * 32),
            record.__setitem__("fingerprint_sha256", "00" * 32),
        ),
    )
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_MISMATCH"


def test_store_ahead_of_checkpoint_catch_up_on_verify(tmp_path: Path, repo_root: Path) -> None:
    svc, _keys = _activated(tmp_path, repo_root)
    stale = copy.deepcopy(try_load_record(tmp_path))
    assert stale is not None
    init_hash_chain(tmp_path)
    ahead = try_load_record(tmp_path)
    assert ahead is not None
    assert ahead["checkpoint"]["event_seq"] > stale["checkpoint"]["event_seq"]
    _pin_path(tmp_path).write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
    result = svc.verify()
    assert result["verify_status"] == "ok"
    restored = try_load_record(tmp_path)
    assert restored is not None
    assert restored["checkpoint"]["event_seq"] == ahead["checkpoint"]["event_seq"]
    assert restored["checkpoint"]["projection_hash_sha256"] == ahead["checkpoint"]["projection_hash_sha256"]


def test_checkpoint_ahead_of_store_is_fail_closed(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    auth = _review_auth(keys["reviewer"], keys["project_id"], "cc" * 16, "reviewer-qa", "T-1000", "approve")
    last_seq = parse_event_store(tmp_path)[-1]["event_seq"]
    _rewrite_pin(tmp_path, lambda record: record["checkpoint"].__setitem__("event_seq", last_seq + 7))
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_ROLLBACK"
    with pytest.raises(ESAAError) as exc:
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth, dry_run=True)
    assert exc.value.code == "TRUST_ROLLBACK"


def test_dry_run_does_not_advance_checkpoint(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    before = copy.deepcopy(try_load_record(tmp_path))
    auth = _review_auth(keys["reviewer"], keys["project_id"], "cd" * 16, "reviewer-qa", "T-1000", "approve")
    result = svc.review_task("T-1000", actor="reviewer-qa", decision="approve", authorization=auth, dry_run=True)
    assert result["status"] == "dry_run"
    after = try_load_record(tmp_path)
    assert after == before


def test_owner_import_rejects_fingerprint_swap(tmp_path: Path, repo_root: Path) -> None:
    _activated(tmp_path, repo_root)
    _other, other_pub = _key()
    with pytest.raises(ESAAError) as exc:
        ESAAService(tmp_path).import_owner_trust_pin(make_pin(public_key_hex=other_pub))
    assert exc.value.code == "TRUST_MISMATCH"


def test_owner_import_rejects_checkpoint_regression(tmp_path: Path, repo_root: Path) -> None:
    svc, keys = _activated(tmp_path, repo_root)
    pin = make_pin(public_key_hex=keys["owner_pub"])
    pin["checkpoint"]["event_seq"] = 0
    with pytest.raises(ESAAError) as exc:
        svc.import_owner_trust_pin(pin)
    assert exc.value.code == "TRUST_ROLLBACK"


def test_cli_trust_import_roundtrip(tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_runtime(tmp_path, repo_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESAA_RUNNER_ID", "grok")
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    _owner, owner_pub = _key()
    _write_anchor(tmp_path, owner_pub)
    trust = _bind_trust_root(tmp_path)
    monkeypatch.setenv(ENV_TRUST_ROOT, str(trust))
    pin_path = tmp_path / "owner-pin.json"
    pin_path.write_text(json.dumps(make_pin(public_key_hex=owner_pub)), encoding="utf-8")
    assert main(["--root", str(tmp_path), "actor", "trust-import", "--pin", str(pin_path)]) == 0
    record = try_load_record(tmp_path)
    assert record is not None
    assert record["fingerprint_sha256"] == public_key_fingerprint(owner_pub)


def test_bootstrap_dry_run_without_effect_requires_pin(tmp_path: Path, repo_root: Path) -> None:
    _copy_runtime(tmp_path, repo_root)
    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    owner, owner_pub = _key()
    _write_anchor(tmp_path, owner_pub)
    _import_owner_pin(tmp_path, owner_pub)
    before = copy.deepcopy(try_load_record(tmp_path))
    result = svc.bootstrap_actor_authority(_bootstrap_auth(owner, owner_pub, "aa" * 16), dry_run=True)
    assert result["status"] == "dry_run"
    assert try_load_record(tmp_path) == before
    assert not any(event["action"] == "actor.bootstrap" for event in parse_event_store(tmp_path))
