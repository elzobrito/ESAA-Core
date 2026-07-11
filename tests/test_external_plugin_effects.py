from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.plugins import activate_roadmap, install_plugin, validate_plugin_dir
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_runtime_files(root: Path, repo_root: Path) -> None:
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


def _external_plugin(plugin_dir: Path) -> Path:
    _write_json(
        plugin_dir / "plugin.json",
        {
            "schema_version": "esaa-plugin/v1",
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "kind": "roadmap_plugin",
            "esaa_core": {"min_version": "0.5.0", "max_version": "<0.6.0"},
            "entrypoints": {
                "roadmap": "roadmap.template.json",
                "input_example": "inputs/demo.local.example.json",
                "input_schema": "schemas/demo-input.schema.json",
            },
            "task_id_namespace": "demo",
            "capabilities": ["planned_tasks", "local_input", "external_effects"],
            "external_targets": [
                {
                    "id": "target_system",
                    "root_input": "system_path",
                    "runtime_contract": "docs/runtime-contract.json",
                    "runtime_uri_prefixes": ["runtime://outputs."],
                    "allowed_write": ["app/**", "tests/**"],
                }
            ],
        },
    )
    _write_json(
        plugin_dir / "roadmap.template.json",
        {
            "project": {"name": "Demo", "audit_scope": "demo"},
            "tasks": [
                {
                    "task_id": "T-001",
                    "task_kind": "impl",
                    "title": "Write external client",
                    "description": "Write a generated file into the target system.",
                    "depends_on": [],
                    "outputs": {
                        "files": ["runtime://outputs.client"],
                        "target": "target_system",
                        "external_files": [
                            {"target": "target_system", "path": "runtime://outputs.client"}
                        ],
                    },
                }
            ],
        },
    )
    _write_json(plugin_dir / "inputs" / "demo.local.example.json", {"system_path": "target"})
    _write_json(
        plugin_dir / "schemas" / "demo-input.schema.json",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["system_path"],
            "properties": {"system_path": {"type": "string", "minLength": 1}},
        },
    )
    return plugin_dir


def _workspace_with_active_plugin(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    _copy_runtime_files(workspace, repo_root)
    plugin_dir = _external_plugin(tmp_path / "plugins" / "demo")
    validate_plugin_dir(plugin_dir, repo_root)
    install_plugin(workspace, str(plugin_dir), repo_root=repo_root)
    input_file = workspace / ".roadmap" / "plugin-inputs" / "demo.default.local.json"
    _write_json(input_file, {"system_path": str(target)})
    activate_roadmap(
        workspace,
        "demo",
        input_path=".roadmap/plugin-inputs/demo.default.local.json",
        repo_root=repo_root,
    )
    _write_json(workspace / "docs" / "runtime-contract.json", {"outputs": {"client": "app/generated.go"}})
    return workspace, target


def test_external_plugin_effect_dry_run_and_commit(tmp_path: Path, repo_root: Path) -> None:
    workspace, target = _workspace_with_active_plugin(tmp_path, repo_root)
    svc = ESAAService(workspace)
    svc.init(force=True, with_demo_tasks=True)
    task_id = "demo-default-T-001"
    content = "package app\n"

    svc.submit(
        {"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}},
        actor="agent-impl",
    )
    output = {
        "activity_event": {
            "action": "complete",
            "task_id": task_id,
            "prior_status": "in_progress",
            "verification": {"checks": ["generated file compiles"]},
        },
        "file_updates": [{"path": "runtime://outputs.client", "content": content}],
    }

    dry_run = svc.submit(output, actor="agent-impl", dry_run=True)
    assert dry_run["status"] == "dry_run"
    assert dry_run["external_effects"] == [
        {
            "target": "target_system",
            "source": "runtime://outputs.client",
            "resolved_path": str((target / "app" / "generated.go").resolve()),
            "target_path": "app/generated.go",
            "allowed": True,
        }
    ]
    assert not (target / "app" / "generated.go").exists()

    result = svc.submit(output, actor="agent-impl")
    assert result["status"] == "accepted"
    assert (target / "app" / "generated.go").read_text(encoding="utf-8") == content
    effects = [
        event["payload"]["effects"][0]
        for event in parse_event_store(workspace)
        if event["action"] == "orchestrator.file.write"
    ]
    assert effects[-1]["effect_scope"] == "external"
    assert effects[-1]["target"] == "target_system"
    assert effects[-1]["target_path"] == "app/generated.go"
    assert effects[-1]["path"] == "runtime://outputs.client"


def test_external_plugin_effect_rejects_path_outside_allowed_write(tmp_path: Path, repo_root: Path) -> None:
    workspace, _ = _workspace_with_active_plugin(tmp_path, repo_root)
    _write_json(workspace / "docs" / "runtime-contract.json", {"outputs": {"client": "private/generated.go"}})
    svc = ESAAService(workspace)
    svc.init(force=True, with_demo_tasks=True)
    task_id = "demo-default-T-001"
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}},
        actor="agent-impl",
    )

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            {
                "activity_event": {
                    "action": "complete",
                    "task_id": task_id,
                    "prior_status": "in_progress",
                    "verification": {"checks": ["blocked"]},
                },
                "file_updates": [{"path": "runtime://outputs.client", "content": "x"}],
            },
            actor="agent-impl",
            dry_run=True,
        )
    assert exc.value.code == "BOUNDARY_VIOLATION"
