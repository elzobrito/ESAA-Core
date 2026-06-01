from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.plugins import (
    activate_roadmap,
    diagnose_plugin,
    install_plugin,
    list_roadmaps,
    scaffold_plugin,
    validate_plugin,
    validate_plugin_dir,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _plugin_package(plugin_dir: Path, plugin_id: str = "security") -> Path:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        plugin_dir / "plugin.json",
        {
            "schema_version": "esaa-plugin/v1",
            "id": plugin_id,
            "name": "Security",
            "version": "1.0.0",
            "kind": "roadmap_plugin",
            "esaa_core": {"min_version": "0.5.0", "max_version": "<0.6.0"},
            "entrypoints": {
                "roadmap": "roadmap.template.json",
                "input_example": f"inputs/{plugin_id}.local.example.json",
                "input_schema": f"schemas/{plugin_id}-input.schema.json",
            },
            "task_id_namespace": plugin_id,
            "capabilities": ["planned_tasks", "local_input"],
        },
    )
    _write_json(
        plugin_dir / "roadmap.template.json",
        {
            "project": {"name": "Security", "audit_scope": "security"},
            "tasks": [
                {
                    "task_id": "T-001",
                    "task_kind": "spec",
                    "title": "Define security baseline",
                    "description": "Document the security baseline.",
                    "depends_on": [],
                    "outputs": {"files": ["docs/security/baseline.md"]},
                }
            ],
        },
    )
    _write_json(plugin_dir / "inputs" / f"{plugin_id}.local.example.json", {"target": "local"})
    _write_json(
        plugin_dir / "schemas" / f"{plugin_id}-input.schema.json",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["target"],
            "properties": {"target": {"type": "string"}},
        },
    )
    return plugin_dir


def test_scaffold_plugin_creates_valid_directory_package(tmp_path: Path, repo_root: Path) -> None:
    result = scaffold_plugin(tmp_path, "security", repo_root=repo_root)

    plugin_dir = tmp_path / "security"
    assert result["status"] == "created"
    assert result["path"] == str(plugin_dir)
    assert (plugin_dir / "plugin.json").is_file()
    assert (plugin_dir / "roadmap.template.json").is_file()
    assert validate_plugin_dir(plugin_dir, repo_root)["valid"] is True


def test_validate_and_install_plugin_accept_local_directory_path(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")
    workspace = tmp_path / "workspace"

    validated = validate_plugin(workspace, str(plugin_dir), repo_root=repo_root)
    installed = install_plugin(workspace, str(plugin_dir), repo_root=repo_root)

    assert validated["source"] == "local"
    assert installed["plugin"]["source"] == "local"
    assert Path(installed["plugin"]["manifest_path"]) == plugin_dir / "plugin.json"


def test_activate_roadmap_validates_explicit_input_against_plugin_schema(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")
    workspace = tmp_path / "workspace"
    install_plugin(workspace, str(plugin_dir), repo_root=repo_root)
    input_file = workspace / ".roadmap" / "plugin-inputs" / "security.default.local.json"
    _write_json(input_file, {"target": "docs"})

    result = activate_roadmap(
        workspace,
        "security",
        execution_id="default",
        input_path=".roadmap/plugin-inputs/security.default.local.json",
        repo_root=repo_root,
    )

    assert result["status"] == "active"
    assert list_roadmaps(workspace, detail=True, repo_root=repo_root)[0]["tasks"][0]["task_id"] == "security-default-T-001"


def test_activate_roadmap_rejects_input_that_fails_plugin_schema(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")
    workspace = tmp_path / "workspace"
    install_plugin(workspace, str(plugin_dir), repo_root=repo_root)
    input_file = workspace / ".roadmap" / "plugin-inputs" / "security.default.local.json"
    _write_json(input_file, {"unexpected": True})

    with pytest.raises(ESAAError) as exc:
        activate_roadmap(
            workspace,
            "security",
            execution_id="default",
            input_path=".roadmap/plugin-inputs/security.default.local.json",
            repo_root=repo_root,
        )

    assert exc.value.code == "PLUGIN_INPUT_INVALID"
    assert "target" in str(exc.value)


def test_validate_plugin_rejects_path_traversal_in_entrypoints(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    manifest["entrypoints"]["roadmap"] = "../roadmap.template.json"
    _write_json(plugin_dir / "plugin.json", manifest)

    with pytest.raises(ESAAError) as exc:
        validate_plugin_dir(plugin_dir, repo_root)

    assert exc.value.code == "PLUGIN_PATH_INVALID"


def test_validate_plugin_rejects_dangerous_output_file_path(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")
    roadmap = json.loads((plugin_dir / "roadmap.template.json").read_text(encoding="utf-8"))
    roadmap["tasks"][0]["outputs"]["files"] = ["../src/app.py", ".roadmap/activity.jsonl"]
    _write_json(plugin_dir / "roadmap.template.json", roadmap)

    with pytest.raises(ESAAError) as exc:
        validate_plugin_dir(plugin_dir, repo_root)

    assert exc.value.code == "PLUGIN_PATH_INVALID"


def test_plugin_doctor_returns_structured_checks(tmp_path: Path, repo_root: Path) -> None:
    plugin_dir = _plugin_package(tmp_path / "plugins" / "security")

    result = diagnose_plugin(tmp_path, str(plugin_dir), repo_root=repo_root)

    assert result["status"] == "ok"
    assert {check["name"] for check in result["checks"]} >= {
        "directory",
        "manifest",
        "roadmap",
        "input_schema",
        "input_example",
        "path_safety",
    }
    assert result["errors"] == []


def test_cli_publication_flow_new_validate_install_activate(tmp_path: Path, repo_root: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "plugin", "new", "security"]) == 0
    created = json.loads(capsys.readouterr().out)
    plugin_dir = Path(created["path"])

    assert main(["--root", str(tmp_path), "plugin", "validate", str(plugin_dir)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["source"] == "local"

    assert main(["--root", str(tmp_path), "plugin", "install", str(plugin_dir)]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["plugin"]["id"] == "security"

    assert main(["--root", str(tmp_path), "plugin", "doctor", str(plugin_dir)]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["status"] == "ok"

    assert main(["--root", str(tmp_path), "roadmap", "activate", "security", "--execution-id", "default"]) == 0
    activated = json.loads(capsys.readouterr().out)
    assert activated["status"] == "active"


def test_cli_can_list_external_catalog_plugins(tmp_path: Path, repo_root: Path, capsys, monkeypatch) -> None:
    catalog = tmp_path / "catalog"
    _plugin_package(catalog / "security" / "1.0.0")
    monkeypatch.setenv("ESAA_PLUGINS_HOME", str(catalog))

    assert main(["--root", str(tmp_path), "plugin", "list", "--available", "--external"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["plugins"] == [
        {
            "id": "security",
            "name": "Security",
            "version": "1.0.0",
            "source": "external",
            "content_hash": result["plugins"][0]["content_hash"],
        }
    ]
