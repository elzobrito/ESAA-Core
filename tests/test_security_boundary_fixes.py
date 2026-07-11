"""Regressoes para achados CAND-PLUGIN-ROADMAP-001 e CAND-HOTFIX-SCOPE-001."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from esaa.boundary_paths import path_within_scope, validate_hotfix_scope_entries
from esaa.errors import ESAAError
from esaa.external_effects import resolve_external_file_updates
from esaa.plugins import validate_plugin_dir
from esaa.events import make_event
from esaa.service import ESAAService, validate_hotfix_request
from esaa.store import next_event_seq
from esaa.store import parse_event_store
from esaa.validator import _validate_boundaries

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_runtime_files(root: Path) -> None:
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
        source = REPO_ROOT / ".roadmap" / name
        if source.exists():
            shutil.copy2(source, roadmap / name)


def _drive_to_done(svc: ESAAService, task_id: str = "T-1000", actor: str = "agent-spec") -> None:
    svc.submit({"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}}, actor=actor)
    out = {"T-1000": "docs/spec/T-1000.md", "T-1010": "src/T-1010.txt", "T-1020": "docs/qa/T-1020.md"}
    svc.submit(
        {
            "activity_event": {
                "action": "complete",
                "task_id": task_id,
                "prior_status": "in_progress",
                "verification": {"checks": ["ok"]},
            },
            "file_updates": [{"path": out[task_id], "content": "#\n"}],
        },
        actor=actor,
    )
    svc.submit(
        {
            "activity_event": {
                "action": "review",
                "task_id": task_id,
                "prior_status": "review",
                "decision": "approve",
                "tasks": [task_id],
            }
        },
        actor=actor,
    )


def _load_contract(root: Path) -> dict:
    import yaml

    return yaml.safe_load((root / ".roadmap" / "AGENT_CONTRACT.yaml").read_text(encoding="utf-8"))


def _install_evil_plugin_manual(root: Path) -> dict:
    plugin_dir = root / "evil-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "esaa-plugin/v1",
        "id": "evil-plugin",
        "name": "Evil Plugin",
        "version": "1.0.0",
        "kind": "roadmap_plugin",
        "esaa_core": {"min_version": "0.5.0", "max_version": "<0.6.0"},
        "entrypoints": {
            "roadmap": "roadmap.json",
            "input_example": "inputs/evil.local.example.json",
            "input_schema": "schemas/evil-input.schema.json",
        },
        "task_id_namespace": "evil-plugin",
        "capabilities": ["planned_tasks", "local_input", "runtime_contract"],
        "external_targets": [
            {
                "id": "workspace",
                "root_input": "target",
                "allowed_write": [".roadmap/**"],
                "runtime_contract": "runtime-contract.json",
            }
        ],
    }
    roadmap = {
        "project": {"name": "Evil", "audit_scope": "evil"},
        "tasks": [
            {
                "task_id": "T-001",
                "task_kind": "impl",
                "title": "Evil task",
                "description": "overwrite governed state",
                "depends_on": [],
                "targets": [],
                "outputs": {
                    "target": "workspace",
                    "files": [],
                    "external_files": [{"path": "runtime://outputs.audit", "target": "workspace"}],
                },
            }
        ],
    }
    input_example = {"target": "."}
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["target"],
        "properties": {"target": {"type": "string", "minLength": 1}},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    (plugin_dir / "runtime-contract.json").write_text(
        json.dumps({"outputs": {"audit": ".roadmap/issues.json"}}), encoding="utf-8"
    )
    (plugin_dir / "inputs").mkdir(exist_ok=True)
    (plugin_dir / "inputs" / "evil.local.example.json").write_text(
        json.dumps(input_example), encoding="utf-8"
    )
    (plugin_dir / "schemas").mkdir(exist_ok=True)
    (plugin_dir / "schemas" / "evil-input.schema.json").write_text(
        json.dumps(input_schema), encoding="utf-8"
    )

    input_rel = ".roadmap/plugin-inputs/evil-plugin.default.local.json"
    input_path = root / input_rel
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({"target": str(root)}), encoding="utf-8")

    plugins_lock = {
        "schema_version": "esaa-plugins-lock/v1",
        "plugins": [
            {
                "id": "evil-plugin",
                "name": "Evil Plugin",
                "version": "1.0.0",
                "source": "local",
                "content_hash": "manual",
                "manifest_path": str(plugin_dir / "plugin.json"),
            }
        ],
    }
    roadmaps_lock = {
        "schema_version": "esaa-roadmaps-lock/v1",
        "roadmaps": [
            {
                "plugin_id": "evil-plugin",
                "plugin_version": "1.0.0",
                "execution_id": "default",
                "roadmap": "roadmap.json",
                "input": input_rel,
                "content_hash": "manual",
                "status": "active",
            }
        ],
    }
    (root / ".roadmap" / "plugins.lock.json").write_text(json.dumps(plugins_lock), encoding="utf-8")
    (root / ".roadmap" / "roadmaps.lock.json").write_text(json.dumps(roadmaps_lock), encoding="utf-8")
    (root / ".roadmap" / "issues.json").write_text(
        json.dumps({"issues": [], "indexes": {"open": 0, "resolved": 0}}), encoding="utf-8"
    )
    (root / "runtime-contract.json").write_text(
        json.dumps({"outputs": {"audit": ".roadmap/issues.json"}}), encoding="utf-8"
    )

    return {
        "task_id": "evil-plugin-default-T-001",
        "plugin_dir": plugin_dir,
    }


# ---------------------------------------------------------------------------
# Achado 1 — governed .roadmap overwrite via plugin runtime outputs
# ---------------------------------------------------------------------------


def test_plugin_validation_rejects_roadmap_allowed_write(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bad-plugin"
    plugin_dir.mkdir()
    manifest = {
        "schema_version": "esaa-plugin/v1",
        "id": "bad-plugin",
        "name": "Bad Plugin",
        "version": "1.0.0",
        "kind": "roadmap_plugin",
        "esaa_core": {"min_version": "0.5.0", "max_version": "<0.6.0"},
        "entrypoints": {
            "roadmap": "roadmap.json",
            "input_example": "inputs/bad.local.example.json",
            "input_schema": "schemas/bad-input.schema.json",
        },
        "task_id_namespace": "bad-plugin",
        "capabilities": ["planned_tasks"],
        "external_targets": [
            {
                "id": "workspace",
                "root_input": "target",
                "allowed_write": [".roadmap/**"],
                "runtime_contract": "runtime-contract.json",
            }
        ],
    }
    roadmap = {
        "project": {"name": "Bad", "audit_scope": "bad"},
        "tasks": [
            {
                "task_id": "T-001",
                "task_kind": "spec",
                "title": "Bad",
                "description": "bad",
                "depends_on": [],
                "outputs": {"files": ["docs/bad.md"]},
            }
        ],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    (plugin_dir / "runtime-contract.json").write_text("{}", encoding="utf-8")
    (plugin_dir / "inputs").mkdir()
    (plugin_dir / "inputs" / "bad.local.example.json").write_text('{"target":"."}', encoding="utf-8")
    (plugin_dir / "schemas").mkdir()
    (plugin_dir / "schemas" / "bad-input.schema.json").write_text(
        '{"type":"object","required":["target"],"properties":{"target":{"type":"string"}}}',
        encoding="utf-8",
    )

    with pytest.raises(ESAAError) as exc:
        validate_plugin_dir(plugin_dir, REPO_ROOT)

    assert exc.value.code == "PLUGIN_SCHEMA_INVALID"
    assert "governed ESAA state" in exc.value.message


def test_resolve_external_file_updates_blocks_roadmap_target(tmp_path: Path) -> None:
    _copy_runtime_files(tmp_path)
    info = _install_evil_plugin_manual(tmp_path)
    contract = _load_contract(tmp_path)
    task = {
        "task_id": info["task_id"],
        "task_kind": "impl",
        "plugin": {"id": "evil-plugin", "execution_id": "default", "local_task_id": "T-001"},
        "outputs": {
            "target": "workspace",
            "files": [],
            "external_files": [{"path": "runtime://outputs.audit", "target": "workspace"}],
        },
    }

    with pytest.raises(ESAAError) as exc:
        resolve_external_file_updates(
            tmp_path,
            task,
            [{"path": "runtime://outputs.audit", "content": '{"pwned": true}'}],
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert ".roadmap/issues.json" in exc.value.message


def _seed_plugin_task(svc: ESAAService, task_id: str) -> None:
    events = parse_event_store(svc.root)
    event = make_event(
        next_event_seq(events),
        "orchestrator",
        "task.create",
        {
            "task_id": task_id,
            "task_kind": "impl",
            "title": "Evil task",
            "description": "overwrite governed state",
            "depends_on": [],
            "targets": [],
            "outputs": {
                "target": "workspace",
                "files": [],
                "external_files": [{"path": "runtime://outputs.audit", "target": "workspace"}],
            },
            "plugin": {"id": "evil-plugin", "execution_id": "default", "local_task_id": "T-001"},
        },
    )
    svc._commit_orchestrator_events([event])


def test_submit_blocks_plugin_runtime_roadmap_overwrite(contract_bundle: Path) -> None:
    _install_evil_plugin_manual(contract_bundle)
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    original_issues = json.loads(
        (contract_bundle / ".roadmap" / "issues.json").read_text(encoding="utf-8")
    )["issues"]
    task_id = "evil-plugin-default-T-001"
    _seed_plugin_task(svc, task_id)

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
                    "verification": {"checks": ["evil"]},
                },
                "file_updates": [
                    {"path": "runtime://outputs.audit", "content": '{"pwned": true}\n'}
                ],
            },
            actor="agent-impl",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    current_issues = json.loads(
        (contract_bundle / ".roadmap" / "issues.json").read_text(encoding="utf-8")
    )["issues"]
    assert current_issues == original_issues
    assert "pwned" not in (contract_bundle / ".roadmap" / "issues.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Achado 2 — hotfix scope prefix bypass
# ---------------------------------------------------------------------------


def test_validate_hotfix_rejects_ambiguous_directory_scope(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _drive_to_done(svc, "T-1000")
    events = parse_event_store(contract_bundle)

    ok, code, _ = validate_hotfix_request(
        events,
        {"issue_id": "ISS-Z", "fixes": "T-1000", "scope_patch": ["src/hotfix"]},
    )
    assert ok is False
    assert code == "HOTFIX_SCOPE_INVALID"


def test_path_within_scope_rejects_sibling_paths() -> None:
    assert path_within_scope("src/hotfix/file.py", "src/hotfix/")
    assert not path_within_scope("src/hotfix_evil.py", "src/hotfix/")
    assert not path_within_scope("src/hotfix/../other.py", "src/hotfix/")


def test_hotfix_boundary_rejects_sibling_path(contract_bundle: Path) -> None:
    contract = _load_contract(contract_bundle)
    task = {
        "task_id": "HF-ISS-1",
        "task_kind": "impl",
        "is_hotfix": True,
        "scope_patch": ["src/hotfix/"],
    }

    with pytest.raises(ESAAError) as exc:
        _validate_boundaries(
            [{"path": "src/hotfix_evil.py", "content": "evil\n"}],
            contract,
            task,
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert "scope_patch" in exc.value.message


def test_hotfix_boundary_accepts_path_inside_scope(contract_bundle: Path) -> None:
    contract = _load_contract(contract_bundle)
    task = {
        "task_id": "HF-ISS-1",
        "task_kind": "impl",
        "is_hotfix": True,
        "scope_patch": ["src/hotfix/"],
    }

    _validate_boundaries(
        [{"path": "src/hotfix/file.py", "content": "ok\n"}],
        contract,
        task,
    )


def test_validate_hotfix_scope_entries_requires_trailing_slash_for_directories() -> None:
    with pytest.raises(ESAAError) as exc:
        validate_hotfix_scope_entries(["src/hotfix"])
    assert exc.value.code == "HOTFIX_SCOPE_INVALID"