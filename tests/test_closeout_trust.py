"""Composition, concurrency and interruption cases omitted by the initial trust tests."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

import pytest
from test_actor_registration import (
    _activated,
    _bootstrap_auth,
    _copy_runtime,
    _import_owner_pin,
    _key,
    _ready_task,
    _write_anchor,
)
from test_trust_rollback import _recompute_chain, _write_events

from esaa.errors import ESAAError
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import init_hash_chain, parse_event_store
from esaa.trust_enrollment import registry_directory as os_registry_directory
from esaa.trust_root import ENV_TRUST_ROOT, advance_checkpoint, bound_record_path, try_load_record


def _before_activation(root, repo):
    _copy_runtime(root, repo)
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=True)
    _ready_task(svc)
    snapshot = {p.name: p.read_bytes() for p in (root / ".roadmap").iterdir() if p.is_file()}
    private, public = _key()
    _write_anchor(root, public)
    _import_owner_pin(root, public)
    return svc, private, public, snapshot


def _restore(root, snapshot):
    for name, content in snapshot.items():
        (root / ".roadmap" / name).write_bytes(content)


@pytest.mark.parametrize("loss", ["unset", "other-root"])
def test_project_rollback_and_config_loss_cannot_restore_legacy(tmp_path, repo_root, monkeypatch, loss):
    svc, private, public, snapshot = _before_activation(tmp_path, repo_root)
    svc.bootstrap_actor_authority(_bootstrap_auth(private, public, os.urandom(16).hex()))
    pin_path = bound_record_path(tmp_path)
    before = pin_path.read_bytes()
    _restore(tmp_path, snapshot)
    if loss == "unset":
        monkeypatch.delenv(ENV_TRUST_ROOT)
    else:
        monkeypatch.setenv(ENV_TRUST_ROOT, str(tmp_path.parent / "unbound-owner-root"))
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] in {"BLOCKED_ENVIRONMENT", "TRUST_MISMATCH"}
    for dry_run in (True, False):
        with pytest.raises(ESAAError):
            svc.review_task("T-1000", actor="agent-qa", decision="approve", dry_run=dry_run)
    assert pin_path.read_bytes() == before


def test_os_registry_location_ignores_caller_home_and_xdg(tmp_path, monkeypatch):
    before = os_registry_directory()
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "fake-xdg"))
    assert os_registry_directory() == before


def test_full_history_commitment_covers_lessons_even_with_recomputed_chain(tmp_path, repo_root):
    svc, _keys = _activated(tmp_path, repo_root)
    init_hash_chain(tmp_path)
    pin_path = bound_record_path(tmp_path)
    before = pin_path.read_bytes()
    events = parse_event_store(tmp_path)
    changed = False
    for event in events:
        if event["action"] == "orchestrator.view.mutate" and event["payload"].get("lessons"):
            event["payload"]["lessons"] = []
            changed = True
            break
    assert changed
    _write_events(tmp_path, _recompute_chain(events))
    assert svc.verify()["error_code"] == "TRUST_MISMATCH"
    assert pin_path.read_bytes() == before


@pytest.mark.parametrize("interruption", ["before_append", "after_append"])
def test_first_activation_intent_prevents_crash_rollback(tmp_path, repo_root, monkeypatch, interruption):
    import esaa.trust_root as trust

    svc, private, public, snapshot = _before_activation(tmp_path, repo_root)
    original_write = trust._write_record
    writes = 0

    def fail_checkpoint(path, record):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("injected checkpoint interruption")
        original_write(path, record)

    original_open = Path.open

    def fail_append(path, mode="r", *args, **kwargs):
        if path == tmp_path / ".roadmap/activity.jsonl" and mode == "a":
            raise OSError("injected append interruption")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as local:
        if interruption == "after_append":
            local.setattr(trust, "_write_record", fail_checkpoint)
        else:
            local.setattr(Path, "open", fail_append)
        with pytest.raises(OSError):
            svc.bootstrap_actor_authority(_bootstrap_auth(private, public, os.urandom(16).hex()))
    pin = try_load_record(tmp_path)
    assert pin is not None and pin["pending_activation"] is not None
    _restore(tmp_path, snapshot)
    result = svc.verify()
    assert result["verify_status"] == "corrupted"
    assert result["error_code"] == "TRUST_ROLLBACK"


def test_concurrent_checkpoint_update_cannot_regress_completed_writer(tmp_path, repo_root, monkeypatch):
    import esaa.store as store
    import esaa.trust_root as trust

    svc, _keys = _activated(tmp_path, repo_root)
    stale = copy.deepcopy(try_load_record(tmp_path))
    svc.create_task("T-A", task_kind="impl", title="a")
    events_a = parse_event_store(tmp_path)
    snapshot_a = {p.name: p.read_bytes() for p in (tmp_path / ".roadmap").iterdir() if p.is_file()}
    pin_path = bound_record_path(tmp_path)
    pin_path.write_text(json.dumps(stale))
    entered_a, release_a, entered_b = threading.Event(), threading.Event(), threading.Event()
    original_write = trust._write_record
    original_acquire = store._acquire_store_lock
    errors = []

    def slow_write(path, record):
        if threading.current_thread().name == "checkpoint-A":
            entered_a.set()
            assert release_a.wait(5)
        original_write(path, record)

    def acquire(path, *args, **kwargs):
        if threading.current_thread().name == "checkpoint-B" and path == pin_path:
            entered_b.set()
        return original_acquire(path, *args, **kwargs)

    def run_a():
        try:
            advance_checkpoint(
                tmp_path, events_a, materialize(events_a)[0]["meta"]["run"]["projection_hash_sha256"]
            )
        except Exception as exc:
            errors.append(exc)

    def run_b():
        try:
            svc.create_task("T-B", task_kind="impl", title="b")
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(trust, "_write_record", slow_write)
    monkeypatch.setattr(store, "_acquire_store_lock", acquire)
    a = threading.Thread(target=run_a, name="checkpoint-A")
    b = threading.Thread(target=run_b, name="checkpoint-B")
    a.start()
    assert entered_a.wait(5)
    b.start()
    try:
        assert entered_b.wait(5)
        assert b.is_alive()
    finally:
        release_a.set()
        a.join(5)
        b.join(5)
    assert not a.is_alive() and not b.is_alive() and not errors
    final_seq = parse_event_store(tmp_path)[-1]["event_seq"]
    assert try_load_record(tmp_path)["checkpoint"]["event_seq"] == final_seq
    _restore(tmp_path, snapshot_a)
    assert svc.verify()["error_code"] == "TRUST_ROLLBACK"
