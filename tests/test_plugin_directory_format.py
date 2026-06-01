from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.plugins import install_plugin, list_available_plugins, validate_plugin_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_plugin(plugin_dir: Path, plugin_id: str = "security") -> Path:
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
    _write_json(plugin_dir / "schemas" / f"{plugin_id}-input.schema.json", {"type": "object"})
    return plugin_dir


def test_plugin_package_is_a_plain_directory_with_plugin_json_at_root(repo_root: Path, tmp_path: Path) -> None:
    plugin_dir = _minimal_plugin(tmp_path / "security")

    result = validate_plugin_dir(plugin_dir, repo_root)

    assert result["valid"] is True
    assert result["id"] == "security"
    assert result["path"] == str(plugin_dir)
    assert result["manifest"]["entrypoints"]["roadmap"] == "roadmap.template.json"


def test_plugin_package_rejects_archive_file_even_with_plugin_extension(repo_root: Path, tmp_path: Path) -> None:
    archive = tmp_path / "security.esaaplugin"
    archive.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ESAAError) as exc:
        validate_plugin_dir(archive, repo_root)

    assert exc.value.code == "PLUGIN_NOT_A_DIRECTORY"


def test_plugin_package_requires_plugin_json_in_directory_root(repo_root: Path, tmp_path: Path) -> None:
    plugin_dir = tmp_path / "security"
    plugin_dir.mkdir()
    _write_json(plugin_dir / "manifest.json", {"id": "security"})

    with pytest.raises(ESAAError) as exc:
        validate_plugin_dir(plugin_dir, repo_root)

    assert exc.value.code == "PLUGIN_NOT_FOUND"
    assert "plugin.json" in str(exc.value)


def test_available_plugin_discovery_ignores_files_and_reads_only_directories(tmp_path: Path) -> None:
    bundled = tmp_path / "src" / "esaa" / "bundled_plugins"
    _minimal_plugin(bundled / "security")
    bundled.mkdir(parents=True, exist_ok=True)
    (bundled / "sso-client.esaaplugin").write_text("archive files are not plugin packages", encoding="utf-8")

    result = list_available_plugins(repo_root=tmp_path)

    assert [plugin["id"] for plugin in result if plugin.get("valid", True)] == ["security"]


def test_install_plugin_lock_points_to_manifest_inside_plugin_directory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _minimal_plugin(repo_root / "src" / "esaa" / "bundled_plugins" / "security")
    workspace = tmp_path / "workspace"

    result = install_plugin(workspace, "security", repo_root=repo_root)

    manifest_path = Path(result["plugin"]["manifest_path"])
    assert manifest_path.name == "plugin.json"
    assert manifest_path.parent.name == "security"
