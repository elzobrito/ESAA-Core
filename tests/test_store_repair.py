"""Durable writes and conservative tail repair (all corruption is in disposable workspaces)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import esaa.durable_io as durable
import esaa.store as store
import esaa.store_runtime as store_runtime
from esaa.cli import main
from esaa.errors import CorruptedStoreError, ESAAError
from esaa.events import make_event
from esaa.service import ESAAService
from esaa.store_repair import repair_event_store


def _initialized(root: Path) -> ESAAService:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "a", outputs=["src/a.txt"])
    return service


def _log(root: Path) -> Path:
    return root / ".roadmap/activity.jsonl"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "fragment", [b'{"schema_version":"0.4.1","event_id":"EV-', b"not JSON\n", b'{"payload":"\xc3']
)
def test_repair_quarantines_only_the_tail_and_restores_verify(contract_bundle: Path, fragment: bytes) -> None:
    service = _initialized(contract_bundle)
    before = _log(contract_bundle).read_bytes()
    seq = service.verify()["last_event_seq"]
    _log(contract_bundle).write_bytes(before + fragment)

    result = repair_event_store(contract_bundle)

    assert result["status"] == "repaired"
    assert result["verify_status"] == "ok"
    assert result["last_event_seq"] == seq
    assert result["truncated_bytes"] == len(fragment)
    assert (contract_bundle / result["backup_path"]).read_bytes() == fragment
    assert _log(contract_bundle).read_bytes() == before
    assert service.verify()["verify_status"] == "ok"
    assert repair_event_store(contract_bundle)["status"] == "unchanged"


def test_dry_run_is_entirely_read_only(contract_bundle: Path) -> None:
    _initialized(contract_bundle)
    _log(contract_bundle).write_bytes(_log(contract_bundle).read_bytes() + b'{"broken":')
    before = _snapshot(contract_bundle)
    result = repair_event_store(contract_bundle, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["repair_needed"] is True
    assert result["verify_status"] == "ok"
    assert _snapshot(contract_bundle) == before
    assert not (contract_bundle / ".roadmap/activity.jsonl.lock").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_missing_store_never_creates_workspace(tmp_path: Path, dry_run: bool) -> None:
    root = tmp_path / "absent"
    with pytest.raises(ESAAError) as exc:
        repair_event_store(root, dry_run=dry_run)
    assert exc.value.code == "EVENT_STORE_MISSING"
    assert not root.exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_invalid_middle_line_is_fatal_and_unchanged(contract_bundle: Path, dry_run: bool) -> None:
    _initialized(contract_bundle)
    lines = _log(contract_bundle).read_bytes().splitlines(keepends=True)
    lines.insert(2, b'{"broken":\n')
    _log(contract_bundle).write_bytes(b"".join(lines))
    before = _snapshot(contract_bundle)
    with pytest.raises(CorruptedStoreError) as exc:
        repair_event_store(contract_bundle, dry_run=dry_run)
    assert exc.value.code == "JSONL_INVALID"
    assert _snapshot(contract_bundle) == before


@pytest.mark.parametrize("last", [b"null\n", b"[]\n", b"{}\n"])
def test_valid_json_tail_is_never_discarded_as_a_torn_write(contract_bundle: Path, last: bytes) -> None:
    _initialized(contract_bundle)
    _log(contract_bundle).write_bytes(_log(contract_bundle).read_bytes() + last)
    before = _snapshot(contract_bundle)
    with pytest.raises(CorruptedStoreError):
        repair_event_store(contract_bundle)
    assert _snapshot(contract_bundle) == before


@pytest.mark.parametrize("kind", ["sequence", "action", "transition", "chain"])
def test_corruption_in_prefix_blocks_repair_without_writes(contract_bundle: Path, kind: str) -> None:
    _initialized(contract_bundle)
    if kind == "chain":
        store_runtime.init_hash_chain(contract_bundle)
    lines = _log(contract_bundle).read_text().splitlines()
    event = json.loads(lines[1])
    if kind == "sequence":
        event["event_seq"] = 999
    elif kind == "action":
        event["action"] = "not.a.real.action"
    elif kind == "transition":
        event["action"] = "claim"
        event["actor"] = "agent-impl"
        event["payload"] = {"task_id": "NONEXISTENT", "prior_status": "todo"}
    else:
        event["payload"]["tampered"] = True
    lines[1] = json.dumps(event)
    _log(contract_bundle).write_text("\n".join(lines) + '\n{"broken":')
    before = _snapshot(contract_bundle)
    with pytest.raises(ESAAError):
        repair_event_store(contract_bundle)
    assert _snapshot(contract_bundle) == before


def test_good_chain_survives_tail_repair(contract_bundle: Path) -> None:
    _initialized(contract_bundle)
    store_runtime.init_hash_chain(contract_bundle)
    ESAAService(contract_bundle).claim_task("T-A", actor="agent-impl")
    before = _log(contract_bundle).read_bytes()
    _log(contract_bundle).write_bytes(before + b'{"truncated":')
    assert repair_event_store(contract_bundle)["verify_status"] == "ok"
    assert store.verify_hash_chain(contract_bundle)["chain_status"] == "ok"
    assert _log(contract_bundle).read_bytes() == before


def test_checkpoint_rollback_is_not_repaired(tmp_path: Path, repo_root: Path) -> None:
    from test_actor_registration import _activated, _ready_task

    service, keys = _activated(tmp_path, repo_root)
    prefix = _log(tmp_path).read_bytes()
    _ready_task(service, keys=keys)  # advance the external checkpoint beyond the captured prefix
    _log(tmp_path).write_bytes(prefix + b'{"truncated":')
    before = _snapshot(tmp_path)
    with pytest.raises(CorruptedStoreError) as exc:
        repair_event_store(tmp_path)
    assert exc.value.code == "TRUST_ROLLBACK"
    assert _snapshot(tmp_path) == before


def test_signed_history_remains_authenticated_during_repair(tmp_path: Path, repo_root: Path) -> None:
    from test_actor_registration import _activated

    _activated(tmp_path, repo_root)
    prefix = _log(tmp_path).read_bytes()
    _log(tmp_path).write_bytes(prefix + b'{"truncated":')
    assert repair_event_store(tmp_path)["verify_status"] == "ok"
    assert _log(tmp_path).read_bytes() == prefix


def test_cli_repair_and_jsonl_hint(contract_bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _initialized(contract_bundle)
    _log(contract_bundle).write_bytes(_log(contract_bundle).read_bytes() + b'{"truncated":')
    with pytest.raises(CorruptedStoreError) as exc:
        store.parse_event_store(contract_bundle)
    assert "esaa store repair" in exc.value.message
    assert main(["--root", str(contract_bundle), "store", "repair"]) == 0
    assert json.loads(capsys.readouterr().out)["verify_status"] == "ok"


def test_operator_policy_applies_before_repair(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _initialized(contract_bundle)
    (contract_bundle / ".roadmap/RUNTIME_POLICY.yaml").write_text('runner_validation: "strict"\n')
    monkeypatch.setenv("ESAA_RUNNER_ID", "codex")
    before = _snapshot(contract_bundle)
    with pytest.raises(ESAAError) as exc:
        repair_event_store(contract_bundle, dry_run=True)
    assert exc.value.code == "OPERATOR_REQUIRED"
    assert _snapshot(contract_bundle) == before


def test_lock_covers_validation_backup_truncation_and_projections(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import esaa.store_repair as repair

    _initialized(contract_bundle)
    _log(contract_bundle).write_bytes(_log(contract_bundle).read_bytes() + b'{"truncated":')
    original = repair.atomic_write_bytes
    seen = []

    def checked(path: Path, content: bytes) -> None:
        assert _log(contract_bundle).with_name("activity.jsonl.lock").is_file()
        seen.append(path)
        original(path, content)

    monkeypatch.setattr(repair, "atomic_write_bytes", checked)
    assert repair_event_store(contract_bundle)["verify_status"] == "ok"
    assert seen[0].parent == contract_bundle / ".roadmap/backups"
    assert seen[1] == _log(contract_bundle)


@pytest.mark.parametrize("failure", ["write_fsync", "replace"])
def test_atomic_projection_failure_preserves_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    path = tmp_path / "roadmap.json"
    path.write_bytes(b'{"old":true}\n')

    def fail(*args) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr(durable.os, "fsync" if failure == "write_fsync" else "replace", fail)
    with pytest.raises(OSError, match="injected"):
        store._write_json(path, {"new": True})
    assert path.read_bytes() == b'{"old":true}\n'
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_projection_retains_bytes_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "roadmap.json"
    path.write_text("old")
    path.chmod(0o640)
    store._write_json(path, {"ação": ["á", 1]})
    assert path.read_bytes() == (json.dumps({"ação": ["á", 1]}, ensure_ascii=False, indent=2) + "\n").encode()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("transactional", [False, True])
def test_append_fsync_happens_before_read_after_write(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch, transactional: bool
) -> None:
    service = _initialized(contract_bundle)
    log_stat = _log(contract_bundle).stat()
    synced = []
    original_fsync = store.os.fsync
    original_verify = store._verify_appended_lines

    def track(descriptor: int) -> None:
        entry = os.fstat(descriptor)
        if (entry.st_dev, entry.st_ino) == (log_stat.st_dev, log_stat.st_ino):
            synced.append(True)
        original_fsync(descriptor)

    def verify(path: Path, expected: list[str]) -> None:
        assert synced, "append must flush and fsync before rereading"
        original_verify(path, expected)

    monkeypatch.setattr(store.os, "fsync", track)
    monkeypatch.setattr(store, "_verify_appended_lines", verify)
    if transactional:
        service.claim_task("T-A", actor="agent-impl")
    else:
        events = store.parse_event_store(contract_bundle)
        store.append_events(
            contract_bundle, [make_event(len(events) + 1, "orchestrator", "verify.start", {})]
        )
    assert synced
