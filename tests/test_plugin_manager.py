from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.plugins import (
    activate_roadmap,
    effective_task_id,
    install_plugin,
    load_active_roadmap_tasks,
    list_available_plugins,
    list_installed_plugins,
    list_roadmaps,
    remove_plugin,
    scaffold_plugin,
    validate_plugin,
)


def test_effective_task_id_uses_dash_namespace() -> None:
    assert effective_task_id("sso-client", "default", "T-001") == "sso-client-default-T-001"


def test_effective_task_id_rejects_colon_components() -> None:
    with pytest.raises(ESAAError) as exc:
        effective_task_id("sso-client", "default:prod", "T-001")
    assert exc.value.code == "PLUGIN_INVALID_ID"


def test_clean_distribution_has_no_bundled_plugins_by_default(repo_root: Path) -> None:
    available = list_available_plugins(repo_root, source_filter="bundled")

    assert available == []


def test_install_plugin_writes_lock_but_does_not_activate_tasks(tmp_path: Path, repo_root: Path) -> None:
    scaffold_plugin(tmp_path, "sso-client", repo_root=repo_root)
    result = install_plugin(tmp_path, "./sso-client", repo_root=repo_root)

    assert result["status"] == "installed"
    assert result["plugin"]["id"] == "sso-client"
    assert list_installed_plugins(tmp_path, repo_root=repo_root)[0]["id"] == "sso-client"
    assert load_active_roadmap_tasks(tmp_path, repo_root=repo_root) is None


def test_activate_roadmap_exposes_namespaced_tasks(tmp_path: Path, repo_root: Path) -> None:
    scaffold_plugin(tmp_path, "sso-client", repo_root=repo_root)
    install_plugin(tmp_path, "./sso-client", repo_root=repo_root)
    result = activate_roadmap(
        tmp_path,
        "sso-client",
        execution_id="default",
        repo_root=repo_root,
    )

    assert result["status"] == "active"
    roadmaps = list_roadmaps(tmp_path, repo_root=repo_root)
    assert roadmaps[0]["status"] == "active"

    seed = load_active_roadmap_tasks(tmp_path, repo_root=repo_root)
    assert seed is not None
    ids = [task["task_id"] for task in seed["tasks"]]
    assert "sso-client-default-T-001" in ids
    first = seed["tasks"][0]
    assert first["plugin"]["id"] == "sso-client"
    assert first["plugin"]["execution_id"] == "default"
    assert first["plugin"]["local_task_id"] == "T-001"
    assert all(":" not in task["task_id"] for task in seed["tasks"])


def test_remove_plugin_removes_active_roadmaps(tmp_path: Path, repo_root: Path) -> None:
    scaffold_plugin(tmp_path, "sso-client", repo_root=repo_root)
    install_plugin(tmp_path, "./sso-client", repo_root=repo_root)
    activate_roadmap(tmp_path, "sso-client", execution_id="default", repo_root=repo_root)

    result = remove_plugin(tmp_path, "sso-client", repo_root=repo_root)

    assert result["status"] == "removed"
    assert list_installed_plugins(tmp_path, repo_root=repo_root) == []
    assert list_roadmaps(tmp_path, repo_root=repo_root) == []


def test_template_roadmap_file_is_not_loaded_as_compat_plugin(tmp_path: Path) -> None:
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir()
    (roadmap_dir / "roadmap.demo.template.json").write_text(
        json.dumps({"project": {"name": "x", "audit_scope": "x"}, "tasks": [{"task_id": "T-001"}]}),
        encoding="utf-8",
    )

    assert load_active_roadmap_tasks(tmp_path) is None
