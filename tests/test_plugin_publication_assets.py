from __future__ import annotations

import tomllib
from pathlib import Path

import esaa.plugins as plugin_module
from esaa.plugins import list_available_plugins


def test_publication_bundle_does_not_require_bundled_plugins(repo_root: Path) -> None:
    bundled_dir = repo_root / "src" / "esaa" / "bundled_plugins"
    ids = {plugin["id"] for plugin in list_available_plugins(repo_root, source_filter="bundled") if plugin.get("valid", True)}

    assert bundled_dir.exists()
    assert ids == set()


def test_plugin_authoring_docs_exist(repo_root: Path) -> None:
    for rel in (
        "docs/plugins/authoring.md",
        "docs/plugins/installing.md",
        "docs/plugins/security.md",
        "docs/plugins/lifecycle.md",
    ):
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        assert "plugin.json" in text
        assert "roadmap.template.json" in text


def test_python_package_data_contains_templates_and_workspace_guides(repo_root: Path) -> None:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["esaa"]

    assert package_data == ["templates/*", "workspace/*"]


def test_bundled_plugin_lookup_falls_back_to_installed_package_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_default_repo_root", lambda: tmp_path / "no-source-tree")

    bundled_dir = plugin_module._bundled_plugins_dir()

    assert bundled_dir == Path(plugin_module.__file__).resolve().parent / "bundled_plugins"


def test_available_plugin_discovery_ignores_cache_directories(tmp_path: Path) -> None:
    bundled = tmp_path / "src" / "esaa" / "bundled_plugins"
    (bundled / "__pycache__").mkdir(parents=True)

    paths = plugin_module._available_plugin_dirs(tmp_path)

    assert all(path.name != "__pycache__" for _, path in paths)
