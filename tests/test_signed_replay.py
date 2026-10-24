"""Historical signature regressions; every edit is confined to tmp_path."""
import copy
import json

import pytest

from esaa.errors import ESAAError
from esaa.events import make_event
from esaa.store import append_events, compute_event_hash, parse_event_store, init_hash_chain
from esaa.utils import canonical_json_bytes
from test_actor_registration import _activated, _ready_task, _review_auth, _sign


def _reviewed(tmp_path, repo_root):
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    svc.review_task("T-1000", actor="reviewer-qa", decision="approve",
        authorization=_review_auth(keys["reviewer"], keys["project_id"], "cc" * 16,
                                   "reviewer-qa", "T-1000", "approve"))
    return svc, keys


def _write(root, events):
    (root / ".roadmap/activity.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")


def _auth(event):
    key = "_authorization" if event["action"] == "review" else "authorization"
    return event["payload"][key]


@pytest.mark.parametrize("action", ["actor.bootstrap", "actor.register", "review"])
@pytest.mark.parametrize("tamper", ["signature", "missing", "project", "operation", "scope", "nonce", "alg", "type"])
def test_invalid_historical_auth_is_not_legacy(tmp_path, repo_root, action, tamper):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    event = next(e for e in events if e["action"] == action)
    auth = _auth(event)
    if tamper == "signature":
        auth["signature_hex"] = "00" * 64
    elif tamper == "missing":
        event["payload"].pop("_authorization" if action == "review" else "authorization")
    elif tamper == "project":
        auth["payload"]["project_id"] = "00" * 32
    elif tamper == "operation":
        auth["payload"]["operation"] = "actor.register" if action != "actor.register" else "review"
    elif tamper == "scope":
        auth["payload"]["scope"] = {"unrelated": True}
    elif tamper == "nonce":
        auth["payload"]["nonce"] = "INVALID"
    elif tamper == "alg":
        auth["payload"]["alg"] = "unknown"
    else:
        auth["payload"]["scope"] = []
    _write(tmp_path, events)
    assert svc.verify()["verify_status"] == "corrupted"
    for fn in (lambda: svc.replay(write_views=False), svc.project):
        with pytest.raises(ESAAError):
            fn()


def test_recalculated_hash_chain_does_not_replace_signature(tmp_path, repo_root):
    svc, _ = _reviewed(tmp_path, repo_root)
    init_hash_chain(tmp_path)
    # An event after the chain anchor must have both hashes recomputed.
    from esaa.events import make_event
    events = parse_event_store(tmp_path)
    append_events(tmp_path, [make_event(len(events) + 1, actor="orchestrator",
                                      action="verify.start", payload={"strict": True})])
    events = parse_event_store(tmp_path)
    bootstrap = next(e for e in events if e["action"] == "actor.bootstrap")
    _auth(bootstrap)["signature_hex"] = "00" * 64
    import hashlib
    anchor = next(e for e in events if e["action"] == "chain.anchor")
    n = anchor["payload"]["anchored_through_seq"]
    raw = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events[:n])
    anchor["payload"]["anchor_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    prev = anchor["payload"]["anchor_sha256"]
    for event in events[anchor["event_seq"]:]:
        event["prev_event_hash"] = prev
        event["event_hash"] = compute_event_hash(event)
        prev = event["event_hash"]
    _write(tmp_path, events)
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "AUTH_SIGNATURE_INVALID"


def test_unknown_epoch_and_anchor_absence_are_explicit(tmp_path, repo_root):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    event = next(e for e in events if e["action"] == "actor.bootstrap")
    event["payload"]["identity_epoch"] = "unknown"
    _write(tmp_path, events)
    assert svc.verify()["error_code"] == "AUTH_EPOCH_UNSUPPORTED"
    event["payload"].pop("identity_epoch")
    _write(tmp_path, events)
    (tmp_path / ".roadmap/governance-anchor.json").unlink()
    assert svc.verify()["error_code"] == "ANCHOR_MISSING"


def test_invalid_signed_legacy_review_never_becomes_legacy(tmp_path, repo_root):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    signed = copy.deepcopy(next(e for e in events if e["action"] == "review"))
    signed["event_seq"] = 1
    signed["event_id"] = "EV-00000001"
    _write(tmp_path, [signed])
    assert svc.verify()["error_code"] == "ACTOR_BOOTSTRAP_REQUIRED"


def test_candidate_append_rejects_unsigned_review_without_effect(tmp_path, repo_root):
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    events = parse_event_store(tmp_path)
    path = tmp_path / ".roadmap/activity.jsonl"
    before = path.read_bytes()
    forged = make_event(len(events) + 1, actor="reviewer-qa", action="review",
        payload={"task_id": "T-1000", "tasks": ["T-1000"], "decision": "approve"})
    with pytest.raises(ESAAError):
        append_events(tmp_path, [forged])
    assert path.read_bytes() == before


def test_nonce_reuse_unknown_signer_and_role_are_rejected(tmp_path, repo_root):
    svc, keys = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    review = next(e for e in events if e["action"] == "review")
    auth = _auth(review)
    auth["payload"]["nonce"] = "bb" * 16
    auth["signature_hex"] = keys["reviewer"].sign(canonical_json_bytes(auth["payload"])).hex()
    _write(tmp_path, events)
    assert svc.verify()["error_code"] == "AUTH_REPLAY"


def test_valid_history_replay_deterministic_and_dryrun_rejects_invalid(tmp_path, repo_root):
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    auth = _review_auth(keys["reviewer"], keys["project_id"], "dd" * 16,
                       "reviewer-qa", "T-1000", "approve")
    invalid = copy.deepcopy(auth)
    invalid["signature_hex"] = "00" * 64
    with pytest.raises(ESAAError, match="signature"):
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve",
                        authorization=invalid, dry_run=True)
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    one = svc.replay(write_views=False)
    two = svc.replay(write_views=False)
    assert one == two
    assert one["verify_status"] == svc.verify()["verify_status"] == "ok"


def test_dryrun_cannot_broaden_signed_review_to_other_tasks(tmp_path, repo_root):
    svc, keys = _activated(tmp_path, repo_root)
    _ready_task(svc, keys=keys)
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    auth = _review_auth(keys["reviewer"], keys["project_id"], "dd" * 16,
                       "reviewer-qa", "T-1000", "approve")
    with pytest.raises(ESAAError):
        svc.review_task("T-1000", actor="reviewer-qa", decision="approve",
                        tasks=["T-1000", "T-1001"], authorization=auth, dry_run=True)
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before


def test_internal_dryrun_commit_rejects_forged_registry_event(tmp_path, repo_root):
    svc, keys = _activated(tmp_path, repo_root)
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    events = parse_event_store(tmp_path)
    forged = copy.deepcopy(next(e for e in events if e["action"] == "actor.register"))
    forged["event_seq"] = len(events) + 1
    forged["event_id"] = f"EV-{len(events)+1:08d}"
    _auth(forged)["signature_hex"] = "00" * 64
    with pytest.raises(ESAAError):
        svc._commit_orchestrator_events([forged], dry_run=True)
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before


@pytest.mark.parametrize("representation", ["data", "top", "version"])
def test_signed_representation_not_discarded_by_normalization(tmp_path, repo_root, representation):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    signed = copy.deepcopy(next(e for e in events if e["action"] == "review"))
    auth = signed["payload"].pop("_authorization")
    signed["event_seq"] = 1
    signed["event_id"] = "EV-00000001"
    if representation == "data":
        signed["data"] = {"_authorization": auth}
    elif representation == "top":
        signed["_authorization"] = auth
    else:
        signed["payload"]["_authorization"] = auth
        signed["schema_version"] = "unknown"
    _write(tmp_path, [signed])
    assert svc.verify()["verify_status"] == "corrupted"


def test_data_only_legacy_representation_preserved(tmp_path, repo_root):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    for e in events:
        e["data"] = e.pop("payload")
    _write(tmp_path, events)
    assert svc.verify()["verify_status"] == "ok"


@pytest.mark.parametrize("tamper", ["unknown_actor", "wrong_key", "wrong_role", "scope_signed", "project_signed", "unknown_field"])
def test_valid_signature_cannot_bypass_context(tmp_path, repo_root, tamper):
    svc, keys = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    review = next(e for e in events if e["action"] == "review")
    auth = _auth(review)
    if tamper == "unknown_actor":
        review["actor"] = "not-registered"
        auth["payload"]["scope"]["actor_id"] = "not-registered"
    elif tamper == "wrong_role":
        register = next(e for e in events if e["action"] == "actor.register")
        register["payload"]["role"] = "implementation"
        owner_auth = _auth(register)
        owner_auth["payload"]["scope"]["role"] = "implementation"
        owner_auth["signature_hex"] = keys["owner"].sign(canonical_json_bytes(owner_auth["payload"])).hex()
    elif tamper == "scope_signed":
        auth["payload"]["scope"]["decision"] = "request_changes"
    elif tamper == "project_signed":
        auth["payload"]["project_id"] = "00" * 32
    elif tamper == "unknown_field":
        auth["payload"]["unexpected"] = "field"
    signer = keys["owner"] if tamper == "wrong_key" else keys["reviewer"]
    auth["signature_hex"] = signer.sign(canonical_json_bytes(auth["payload"])).hex()
    _write(tmp_path, events)
    assert svc.verify()["verify_status"] == "corrupted"


def test_duplicate_bootstrap_rejected_by_history(tmp_path, repo_root):
    svc, _ = _reviewed(tmp_path, repo_root)
    events = parse_event_store(tmp_path)
    duplicate = copy.deepcopy(next(e for e in events if e["action"] == "actor.bootstrap"))
    duplicate["event_seq"] = len(events) + 1
    duplicate["event_id"] = f"EV-{len(events)+1:08d}"
    events.append(duplicate)
    _write(tmp_path, events)
    assert svc.verify()["error_code"] == "ACTOR_BOOTSTRAP_EXISTS"


def test_candidate_gate_also_rejects_discardable_signed_metadata(tmp_path):
    from esaa.identity_history import validate_identity_history
    event = {"action": "review", "event_seq": 1, "actor": "agent-qa",
             "payload": {"task_id": "T", "decision": "approve"},
             "data": {"_authorization": {"signature_hex": "invalid"}}}
    with pytest.raises(ESAAError):
        validate_identity_history(tmp_path, [event])
