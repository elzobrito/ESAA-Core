from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import esaa.service_core as service_core_module
from esaa.errors import ESAAError
from esaa.file_effects import STAGING_DIR, verify_artifact
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _complete_output(content: str = "# Atomic\n") -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": "T-1000",
            "prior_status": "in_progress",
            "verification": {"checks": ["atomic file effect"]},
        },
        "file_updates": [{"path": "docs/spec/T-1000.md", "content": content}],
    }


def _raise_append_failure(*_args, **_kwargs) -> None:
    raise ESAAError("STORE_APPEND_FAILED", "simulated append failure")


def _staged_files(root: Path) -> list[Path]:
    staging = root / STAGING_DIR
    if not staging.exists():
        return []
    return list(staging.glob("stage-*.tmp"))


def test_submit_does_not_write_final_file_when_append_fails(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    monkeypatch.setattr(service_core_module, "append_events", _raise_append_failure)
    monkeypatch.setattr(service_core_module, "append_transactional", _raise_append_failure, raising=False)

    with pytest.raises(ESAAError) as exc:
        svc.submit(_complete_output(), actor="agent-spec")

    assert exc.value.code == "STORE_APPEND_FAILED"
    assert not (contract_bundle / "docs/spec/T-1000.md").exists()
    assert _staged_files(contract_bundle) == []


def test_run_does_not_write_final_file_when_append_fails(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.run(steps=1)

    monkeypatch.setattr(service_core_module, "append_events", _raise_append_failure)
    monkeypatch.setattr(service_core_module, "append_transactional", _raise_append_failure, raising=False)

    with pytest.raises(ESAAError) as exc:
        svc.run(steps=1)

    assert exc.value.code == "STORE_APPEND_FAILED"
    assert not (contract_bundle / "docs/spec/T-1000.md").exists()
    assert _staged_files(contract_bundle) == []


def test_submit_file_write_event_contains_effect_hash_and_artifact(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )

    content = "# Atomic\n"
    svc.submit(_complete_output(content), actor="agent-spec")

    events = parse_event_store(contract_bundle)
    write_event = next(event for event in events if event["action"] == "orchestrator.file.write")
    payload = write_event["payload"]
    assert payload["task_id"] == "T-1000"
    assert payload["files"] == ["docs/spec/T-1000.md"]

    effect = payload["effects"][0]
    assert effect["path"] == "docs/spec/T-1000.md"
    assert effect["before_sha256"] is None
    assert effect["after_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert effect["bytes"] == len(content.encode("utf-8"))
    assert effect["encoding"] == "utf-8"
    assert effect["artifact_sha256"]
    assert effect["artifact_path"].startswith(".roadmap/artifacts/file-effects/")

    ok, error = verify_artifact(contract_bundle, effect["artifact_path"])
    assert ok is True
    assert error is None
    assert (contract_bundle / "docs/spec/T-1000.md").read_text(encoding="utf-8") == content
