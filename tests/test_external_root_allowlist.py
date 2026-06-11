from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from esaa.errors import ESAAError
from esaa.plugins import validate_plugin_dir
from esaa.service import ESAAService
from test_external_plugin_effects import _external_plugin, _workspace_with_active_plugin, _write_json


def _set_external_policy(workspace: Path, **external_effects: object) -> None:
    policy_path = workspace / ".roadmap" / "RUNTIME_POLICY.yaml"
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    data["external_effects"] = external_effects
    policy_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _claim_external_task(workspace: Path) -> ESAAService:
    svc = ESAAService(workspace)
    svc.init(force=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "demo-default-T-001", "prior_status": "todo"}},
        actor="agent-impl",
    )
    return svc


def _complete_output(content: str = "package app\n") -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": "demo-default-T-001",
            "prior_status": "in_progress",
            "verification": {"checks": ["generated"]},
        },
        "file_updates": [{"path": "runtime://outputs.client", "content": content}],
    }


def test_external_root_outside_allowlist_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    workspace, _target = _workspace_with_active_plugin(tmp_path, repo_root)
    _set_external_policy(workspace, allowed_roots=[], allow_glob_wildcard=False)
    svc = _claim_external_task(workspace)

    with pytest.raises(ESAAError) as excinfo:
        svc.submit(_complete_output(), actor="agent-impl", dry_run=True)

    assert excinfo.value.code == "EXTERNAL_ROOT_NOT_ALLOWED"


def test_external_root_inside_allowlist_is_resolved_in_dry_run(tmp_path: Path, repo_root: Path) -> None:
    workspace, target = _workspace_with_active_plugin(tmp_path, repo_root)
    _set_external_policy(workspace, allowed_roots=[str(target)], allow_glob_wildcard=False)
    svc = _claim_external_task(workspace)

    result = svc.submit(_complete_output(), actor="agent-impl", dry_run=True)

    assert result["status"] == "dry_run"
    assert result["external_effects"][0]["resolved_path"] == str((target / "app" / "generated.go").resolve())
    assert not (target / "app" / "generated.go").exists()


def test_dangerous_allowed_write_wildcard_is_rejected_by_plugin_validation(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _external_plugin(tmp_path / "plugins" / "demo")
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["external_targets"][0]["allowed_write"] = ["**"]
    _write_json(manifest_path, manifest)

    with pytest.raises(ESAAError) as excinfo:
        validate_plugin_dir(plugin_dir, repo_root)

    assert excinfo.value.code == "PLUGIN_SCHEMA_INVALID"


def test_external_runtime_contract_cannot_traverse_target_root(tmp_path: Path, repo_root: Path) -> None:
    workspace, target = _workspace_with_active_plugin(tmp_path, repo_root)
    _set_external_policy(workspace, allowed_roots=[str(target)], allow_glob_wildcard=False)
    _write_json(workspace / "docs" / "runtime-contract.json", {"outputs": {"client": "../evil.go"}})
    svc = _claim_external_task(workspace)

    with pytest.raises(ESAAError) as excinfo:
        svc.submit(_complete_output(), actor="agent-impl", dry_run=True)

    assert excinfo.value.code in {"PLUGIN_PATH_INVALID", "BOUNDARY_VIOLATION"}
    assert not (target.parent / "evil.go").exists()
