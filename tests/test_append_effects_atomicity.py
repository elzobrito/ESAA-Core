"""Regression tests for batch schema validation before file/artifact/log effects (HF-ISS-AUD-O2-APPEND-EFFECTS-20261113)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from esaa import store_runtime
from esaa.activity_admin import apply_activity_clear, plan_activity_clear
from esaa.bootstrap import bootstrap_workspace
from esaa.errors import ESAAError
from esaa.service import ESAAService


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


def _seed_claimed_task(
    root: Path,
    task_id: str = "T-ATOM",
    target_file: str = "src/atom.py",
    *,
    executable_checks: list[str] | None = None,
) -> ESAAService:
    bootstrap_workspace(root)
    svc = ESAAService(root)
    svc.init()
    svc.create_task(
        task_id=task_id,
        task_kind="impl",
        title="Atomicity task",
        description="Test deferred effects",
        outputs=[target_file],
        executable_checks=executable_checks,
    )
    svc.claim_task(task_id, actor="agent-impl")
    return svc


def _ver_config() -> dict:
    return {
        "checks": [
            {
                "id": "unit",
                "image": "python@sha256:" + "0" * 64,
                "command": ["python3", "-c", "print('ok')"],
                "inputs": ["src/**"],
            }
        ],
    }


def test_submission_invalid_final_event_leaves_zero_artifacts_or_files(tmp_path: Path) -> None:
    svc = _seed_claimed_task(tmp_path)
    before = _snapshot_tree(tmp_path)

    orig_validate = store_runtime.validate_event_for_append

    def fail_on_file_write(event: dict) -> None:
        if event.get("action") == "orchestrator.file.write":
            raise ESAAError("SCHEMA_INVALID", "forced invalid final batch event")
        orig_validate(event)

    patched = dataclasses.replace(store_runtime.DEFAULT_STORE_HOOKS, validate_append_event=fail_on_file_write)
    with patch.object(store_runtime, "DEFAULT_STORE_HOOKS", patched):
        with pytest.raises(ESAAError) as exc:
            svc.submit(
                {
                    "activity_event": {
                        "action": "complete",
                        "task_id": "T-ATOM",
                        "prior_status": "in_progress",
                        "verification": {"checks": ["pytest -q"]},
                    },
                    "file_updates": [{"path": "src/atom.py", "content": "print(1)\n"}],
                },
                actor="agent-impl",
            )
        assert exc.value.code == "SCHEMA_INVALID"

    after = _snapshot_tree(tmp_path)
    assert not (tmp_path / "src" / "atom.py").exists()
    assert (
        not list((tmp_path / ".roadmap" / "artifacts").glob("*.json"))
        if (tmp_path / ".roadmap" / "artifacts").exists()
        else True
    )
    assert (
        not list((tmp_path / ".roadmap" / "staging").glob("*"))
        if (tmp_path / ".roadmap" / "staging").exists()
        else True
    )
    for k, v in before.items():
        if not k.startswith(".roadmap/"):
            assert after.get(k) == v


def test_verification_configure_invalid_final_event_leaves_zero_effects(tmp_path: Path) -> None:
    svc = _seed_claimed_task(tmp_path)
    before = _snapshot_tree(tmp_path)

    orig_validate = store_runtime.validate_event_for_append

    def fail_on_file_write(event: dict) -> None:
        if event.get("action") == "orchestrator.file.write":
            raise ESAAError("SCHEMA_INVALID", "forced invalid verification.configure batch event")
        orig_validate(event)

    patched = dataclasses.replace(store_runtime.DEFAULT_STORE_HOOKS, validate_append_event=fail_on_file_write)
    with patch(
        "esaa.verification_service.schema_upgrades",
        return_value=[{"path": ".roadmap/agent_result.schema.json", "content": '{"upgraded": true}\n'}],
    ):
        with patch.object(store_runtime, "DEFAULT_STORE_HOOKS", patched):
            with pytest.raises(ESAAError) as exc:
                svc.verification_enable(_ver_config())
            assert exc.value.code == "SCHEMA_INVALID"

    after = _snapshot_tree(tmp_path)
    assert after == before


def test_verification_run_invalid_event_writes_zero_logs_and_valid_run_recovers(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path)
    svc = ESAAService(tmp_path)
    svc.init()
    svc.verification_enable(_ver_config())
    svc.create_task(
        task_id="T-ATOM",
        task_kind="impl",
        title="Atomicity task",
        description="Test deferred effects",
        outputs=["src/atom.py"],
        executable_checks=["unit"],
    )
    svc.claim_task("T-ATOM", actor="agent-impl")
    before = _snapshot_tree(tmp_path)

    orig_validate = store_runtime.validate_event_for_append

    def fail_on_ver_run(event: dict) -> None:
        if event.get("action") == "verification.run":
            raise ESAAError("SCHEMA_INVALID", "forced invalid verification.run")
        orig_validate(event)

    candidate = {
        "activity_event": {
            "action": "complete",
            "task_id": "T-ATOM",
            "prior_status": "in_progress",
            "verification": {"checks": ["unit"]},
        },
        "file_updates": [{"path": "src/atom.py", "content": "x = 1\n"}],
    }

    fake_exec = {
        "id": "unit",
        "status": "passed",
        "exit_code": 0,
        "stdout": "ok\n",
        "stderr": "",
        "duration_ms": 5,
    }
    patched = dataclasses.replace(store_runtime.DEFAULT_STORE_HOOKS, validate_append_event=fail_on_ver_run)
    with patch("esaa.verification_executor.execute_check", side_effect=lambda *a, **k: dict(fake_exec)):
        with patch.object(store_runtime, "DEFAULT_STORE_HOOKS", patched):
            with pytest.raises(ESAAError) as exc:
                svc.verification_run("T-ATOM", candidate, actor="agent-impl")
            assert exc.value.code == "SCHEMA_INVALID"

        after = _snapshot_tree(tmp_path)
        assert after == before

        res = svc.verification_run("T-ATOM", candidate, actor="agent-impl")
    found = svc.verification_result(res["run_id"])
    assert found["run_id"] == res["run_id"]
    assert found["status"] == "passed"


def test_execution_run_invalid_final_event_writes_zero_effects(tmp_path: Path) -> None:
    svc = _seed_claimed_task(tmp_path)
    svc.release_task("T-ATOM", reason="reset for execution run")
    before = _snapshot_tree(tmp_path)

    orig_validate = store_runtime.validate_event_for_append

    def fail_on_file_write(event: dict) -> None:
        if event.get("action") == "orchestrator.file.write":
            raise ESAAError("SCHEMA_INVALID", "forced invalid execution batch")
        orig_validate(event)

    class FakeAdapter:
        agent_id = "agent-impl"

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, context: dict) -> dict:
            self.calls += 1
            if self.calls == 1:
                return {
                    "activity_event": {
                        "action": "claim",
                        "task_id": "T-ATOM",
                        "prior_status": "todo",
                    }
                }
            return {
                "activity_event": {
                    "action": "complete",
                    "task_id": "T-ATOM",
                    "prior_status": "in_progress",
                    "verification": {"checks": ["pytest -q"]},
                },
                "file_updates": [{"path": "src/atom.py", "content": "x = 2\n"}],
            }

    svc_with_adapter = ESAAService(tmp_path, adapter=FakeAdapter())
    svc_with_adapter.run(steps=1)  # claim T-ATOM
    before = _snapshot_tree(tmp_path)
    patched = dataclasses.replace(store_runtime.DEFAULT_STORE_HOOKS, validate_append_event=fail_on_file_write)
    with patch.object(store_runtime, "DEFAULT_STORE_HOOKS", patched):
        with pytest.raises(ESAAError) as exc:
            svc_with_adapter.run(steps=1)
        assert exc.value.code == "SCHEMA_INVALID"

    after = _snapshot_tree(tmp_path)
    assert after == before


def test_activity_clear_invalid_seed_leaves_store_and_backup_untouched(tmp_path: Path) -> None:
    _seed_claimed_task(tmp_path)
    before = _snapshot_tree(tmp_path)
    plan = plan_activity_clear(tmp_path, force=True, dry_run=False, backup_dir=".roadmap/backups")

    with patch(
        "esaa.event_schema.validate_event_for_append", side_effect=ESAAError("SCHEMA_INVALID", "bad seed")
    ):
        with pytest.raises(ESAAError) as exc:
            apply_activity_clear(tmp_path, plan)
        assert exc.value.code == "SCHEMA_INVALID"

    after = _snapshot_tree(tmp_path)
    assert after == before


def test_submission_stale_retry_commits_artifacts_and_files_cleanly(tmp_path: Path) -> None:
    svc = _seed_claimed_task(tmp_path)
    orig_append = store_runtime.append_transactional
    calls = {"n": 0}

    def stale_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ESAAError("STALE_STATE_SEQ", "simulated conflict")
        return orig_append(*args, **kwargs)

    with patch.object(store_runtime, "append_transactional", side_effect=stale_once):
        with patch("esaa.service_core.append_transactional", side_effect=stale_once):
            res = svc.submit(
                {
                    "activity_event": {
                        "action": "complete",
                        "task_id": "T-ATOM",
                        "prior_status": "in_progress",
                        "verification": {"checks": ["pytest -q"]},
                    },
                    "file_updates": [{"path": "src/atom.py", "content": "x = 42\n"}],
                },
                actor="agent-impl",
            )
    assert res["status"] == "accepted"
    assert calls["n"] == 2
    assert (tmp_path / "src" / "atom.py").read_text(encoding="utf-8") == "x = 42\n"
    assert svc.verify_full()["verify_status"] == "ok"
