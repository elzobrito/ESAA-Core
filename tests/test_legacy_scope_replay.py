"""HF-ISS-ESAA-B21-LEGACY-ABS-SCOPE — legacy absolute scope_patch replay."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.boundary_paths import legacy_unsafe_scope_entries, validate_hotfix_scope_entries
from esaa.errors import ESAAError
from esaa.service import ESAAService

LEGACY_SCOPE = "/home/user/.local/share/applications/"


def _drive_to_done(svc: ESAAService, task_id: str = "T-1000", actor: str = "agent-spec") -> None:
    svc.submit({"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}}, actor=actor)
    svc.submit({"activity_event": {
        "action": "complete", "task_id": task_id, "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor=actor)
    svc.submit({"activity_event": {
        "action": "review", "task_id": task_id, "prior_status": "review",
        "decision": "approve", "tasks": [task_id],
    }}, actor=actor)


def _hotfix_store(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc)
    svc.report_issue("T-1000", "agent-qa", "ISS-LEG", "high", "legacy", "sym", ["r"])
    svc.create_hotfix(issue_id="ISS-LEG", fixes="T-1000", scope_patch=["src/hotfix/"])
    return svc


def _rewrite_hotfix_scope(root: Path, scope: list[str]) -> None:
    path = root / ".roadmap" / "activity.jsonl"
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            event = json.loads(line)
            payload = event.get("payload") or {}
            if payload.get("is_hotfix") and "scope_patch" in payload:
                payload["scope_patch"] = scope
            line = json.dumps(event, ensure_ascii=False)
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_strict_validation_rejects_absolute_scope() -> None:
    with pytest.raises(ESAAError) as exc:
        validate_hotfix_scope_entries([LEGACY_SCOPE])
    assert exc.value.code == "HOTFIX_SCOPE_INVALID"


def test_legacy_validation_preserves_absolute_scope() -> None:
    assert validate_hotfix_scope_entries([LEGACY_SCOPE], legacy=True) == [LEGACY_SCOPE]
    assert legacy_unsafe_scope_entries([LEGACY_SCOPE, "src/ok/"]) == [LEGACY_SCOPE]


def test_legacy_replay_verify_ok_with_warning(contract_bundle: Path) -> None:
    svc = _hotfix_store(contract_bundle)
    _rewrite_hotfix_scope(contract_bundle, [LEGACY_SCOPE])
    svc.project()
    result = svc.verify()
    assert result["verify_status"] == "ok"
    warnings = result.get("warnings", [])
    assert warnings and warnings[0]["code"] == "LEGACY_SCOPE_PATCH_UNSAFE"
    assert warnings[0]["entries"] == [LEGACY_SCOPE]


def test_clean_store_has_no_warnings(contract_bundle: Path) -> None:
    svc = _hotfix_store(contract_bundle)
    result = svc.verify()
    assert result["verify_status"] == "ok"
    assert "warnings" not in result


def test_new_hotfix_create_rejects_absolute_scope(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc)
    svc.report_issue("T-1000", "agent-qa", "ISS-NEW", "high", "new", "sym", ["r"])
    with pytest.raises(ESAAError) as exc:
        svc.create_hotfix(issue_id="ISS-NEW", fixes="T-1000", scope_patch=[LEGACY_SCOPE])
    assert exc.value.code == "HOTFIX_SCOPE_INVALID"


def test_amend_rejects_absolute_scope_on_legacy_hotfix(contract_bundle: Path) -> None:
    svc = _hotfix_store(contract_bundle)
    _rewrite_hotfix_scope(contract_bundle, [LEGACY_SCOPE])
    svc.project()
    with pytest.raises(ESAAError) as exc:
        svc.amend_task("HF-ISS-LEG", scope_patch=[LEGACY_SCOPE])
    assert exc.value.code == "HOTFIX_SCOPE_INVALID"
