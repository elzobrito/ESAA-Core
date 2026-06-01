from __future__ import annotations

from pathlib import Path


def test_gitignore_keeps_canonical_esaa_files_tracked(repo_root: Path) -> None:
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".roadmap/activity.jsonl" not in text
    assert ".roadmap/roadmap.json" not in text
    assert ".roadmap/backups/" in text
    assert "*.lock" in text


def test_repository_hygiene_doc_exists(repo_root: Path) -> None:
    doc = repo_root / "docs/operations/repository-hygiene.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "Never ignore `.roadmap/activity.jsonl`" in text


def test_readme_separates_tracked_layout_from_runtime_created_paths(repo_root: Path) -> None:
    text = (repo_root / "readme.md").read_text(encoding="utf-8")
    assert "Tracked source and governance files in the reference repository" in text
    assert "Runtime-created paths may not exist in a clean checkout" in text

    tracked_section = text.split("Runtime-created paths may not exist in a clean checkout", 1)[0]
    assert ".roadmap/plugins.lock.json" not in tracked_section
    assert ".roadmap/roadmaps.lock.json" not in tracked_section
    assert ".roadmap/plugin-inputs/" not in tracked_section
    assert ".roadmap/snapshots/" not in tracked_section
    assert "docs/spec/" not in tracked_section
    assert "docs/qa/" not in tracked_section


def test_readme_uses_current_file_effect_recovery_command(repo_root: Path) -> None:
    text = (repo_root / "readme.md").read_text(encoding="utf-8")
    assert "esaa effects recover" in text
    legacy_command = "esaa " + "recover" + "-file-effects"
    assert legacy_command not in text
