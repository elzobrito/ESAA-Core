from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path

import pytest
import yaml

import esaa
from esaa.bootstrap_guides import (
    GUIDE_MARKER_CONTRACT_BEGIN,
    GUIDE_MARKER_CONTRACT_END,
    GUIDE_MARKER_PROJECT_BEGIN,
    GUIDE_MARKER_PROJECT_END,
    extract_regions,
    validate_markers,
)
from esaa.bootstrap import AGENT_GUIDE_TEMPLATE_FILES, GOVERNANCE_TEMPLATE_FILES, bootstrap_workspace
from esaa.cli import main
from esaa.constants import PACKAGE_VERSION
from esaa.errors import ESAAError
from esaa.service import ESAAService


ESSENTIAL_GOVERNANCE_FILES = (
    "STORAGE_POLICY.yaml",
    "PROJECTION_SPEC.md",
    "PARCER_PROFILE.agent-docs.yaml",
    "PARCER_PROFILE.agent-spec.yaml",
    "PARCER_PROFILE.agent-impl.yaml",
    "PARCER_PROFILE.agent-qa.yaml",
    "PARCER_PROFILE.orchestrator-runtime.yaml",
)


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def test_bootstrap_creates_required_governance_files(tmp_path: Path) -> None:
    result = bootstrap_workspace(tmp_path, profile="public")

    assert result["status"] == "bootstrapped"
    assert result["profile"] == "public"
    expected_files = [f".roadmap/{name}" for name in GOVERNANCE_TEMPLATE_FILES]
    expected_files.extend(target for _source, target in AGENT_GUIDE_TEMPLATE_FILES)
    assert sorted(result["files_written"]) == sorted(expected_files)
    assert set(ESSENTIAL_GOVERNANCE_FILES) <= set(GOVERNANCE_TEMPLATE_FILES)
    for name in GOVERNANCE_TEMPLATE_FILES:
        assert (tmp_path / ".roadmap" / name).exists()
    for name in ESSENTIAL_GOVERNANCE_FILES:
        assert (tmp_path / ".roadmap" / name).exists()

    assert not (tmp_path / ".roadmap" / "activity.jsonl").exists()
    assert not (tmp_path / ".roadmap" / "roadmap.json").exists()
    assert not (tmp_path / ".roadmap" / "issues.json").exists()
    assert not (tmp_path / ".roadmap" / "lessons.json").exists()


def test_bootstrap_creates_agent_guidance_files(tmp_path: Path) -> None:
    result = bootstrap_workspace(tmp_path, profile="public")

    assert "README.md" in result["files_written"]
    assert "AGENTS.md" in result["files_written"]
    assert ".claude/CLAUDE.md" in result["files_written"]
    assert (tmp_path / "README.md").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".claude" / "CLAUDE.md").is_file()
    assert not (tmp_path / ".claude" / "settings.local.json").exists()

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    claude = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Contrato operacional ESAA" in agents
    assert "Contrato operacional ESAA" in claude
    assert "O ESAA não usa MCP" in agents
    assert "O ESAA não usa MCP" in claude
    assert "# ESAA" in readme


def test_bootstrap_refuses_existing_files_without_force(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path, profile="public")

    with pytest_raises_esaa("BOOTSTRAP_TARGET_EXISTS"):
        bootstrap_workspace(tmp_path, profile="public")


def test_bootstrap_never_overwrites_event_store_or_read_models(tmp_path: Path) -> None:
    roadmap = tmp_path / ".roadmap"
    roadmap.mkdir()
    protected = {
        "activity.jsonl": "event-store\n",
        "roadmap.json": '{"protected":"roadmap"}\n',
        "issues.json": '{"protected":"issues"}\n',
        "lessons.json": '{"protected":"lessons"}\n',
    }
    for name, content in protected.items():
        (roadmap / name).write_text(content, encoding="utf-8")

    bootstrap_workspace(tmp_path, profile="production", force=True)

    for name, content in protected.items():
        assert (roadmap / name).read_text(encoding="utf-8") == content


def test_bootstrap_force_only_overwrites_allowlisted_governance_files(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path, profile="public")
    target = tmp_path / ".roadmap" / "AGENT_CONTRACT.yaml"
    target.write_text("broken: true\n", encoding="utf-8")

    result = bootstrap_workspace(tmp_path, profile="production", force=True)

    assert ".roadmap/AGENT_CONTRACT.yaml" in result["files_written"]
    assert "allowed_agent_actions" in target.read_text(encoding="utf-8")
    policy = yaml.safe_load((tmp_path / ".roadmap" / "RUNTIME_POLICY.yaml").read_text(encoding="utf-8"))
    assert policy["review_authorization"] == "qa_role"


def test_bootstrap_preserve_guides_ignores_existing_guides_without_force(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("local agent rules\n", encoding="utf-8")

    result = bootstrap_workspace(tmp_path, profile="public", preserve_guides=True)

    assert result["guide_mode"] == "preserve"
    assert "AGENTS.md" in result["files_preserved"]
    assert "AGENTS.md" not in result["files_written"]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "local agent rules\n"
    assert (tmp_path / ".roadmap" / "AGENT_CONTRACT.yaml").is_file()
    assert (tmp_path / ".claude" / "CLAUDE.md").is_file()


def test_bootstrap_preserve_guides_force_refreshes_governance_only(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path, profile="public")
    (tmp_path / "AGENTS.md").write_text("keep me\n", encoding="utf-8")
    (tmp_path / ".roadmap" / "AGENT_CONTRACT.yaml").write_text("broken: true\n", encoding="utf-8")

    result = bootstrap_workspace(tmp_path, profile="production", force=True, preserve_guides=True)

    assert result["guide_mode"] == "preserve"
    assert "AGENTS.md" in result["files_preserved"]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "keep me\n"
    assert "allowed_agent_actions" in (tmp_path / ".roadmap" / "AGENT_CONTRACT.yaml").read_text(
        encoding="utf-8"
    )


def test_bootstrap_merge_guides_wraps_existing_project_content(tmp_path: Path) -> None:
    original = "# App\n\nLocal context.\n"
    (tmp_path / "AGENTS.md").write_text(original, encoding="utf-8")

    result = bootstrap_workspace(tmp_path, profile="public", merge_guides=True)

    merged = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert result["guide_mode"] == "merge"
    assert "AGENTS.md" in result["files_merged"]
    assert GUIDE_MARKER_CONTRACT_BEGIN in merged
    assert GUIDE_MARKER_CONTRACT_END in merged
    assert GUIDE_MARKER_PROJECT_BEGIN in merged
    assert GUIDE_MARKER_PROJECT_END in merged
    contract, project = extract_regions(merged)
    assert "Contrato operacional ESAA" in contract
    assert project == "\n" + original


def test_bootstrap_merge_guides_force_updates_contract_and_preserves_project(tmp_path: Path) -> None:
    bootstrap_workspace(tmp_path, profile="public", merge_guides=True)
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    _contract, project_before = extract_regions(first)
    changed = first.replace("Contrato operacional ESAA", "Contrato operacional ESAA atualizado", 1)
    (tmp_path / "AGENTS.md").write_text(changed, encoding="utf-8")

    bootstrap_workspace(tmp_path, profile="public", force=True, merge_guides=True)

    after = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    contract_after, project_after = extract_regions(after)
    assert "Contrato operacional ESAA atualizado" not in contract_after
    assert "Contrato operacional ESAA" in contract_after
    assert project_after == project_before


def test_bootstrap_merge_readme_uses_short_contract(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Product\n\nOwn docs.\n", encoding="utf-8")

    bootstrap_workspace(tmp_path, profile="public", merge_guides=True)

    contract, project = extract_regions((tmp_path / "README.md").read_text(encoding="utf-8"))
    assert "Este projeto usa ESAA" in contract
    assert "Event Sourcing for Autonomous Agents" not in contract
    assert project == "\n# Product\n\nOwn docs.\n"


def test_bootstrap_merge_guides_notes_root_claude_ignored(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("root claude\n", encoding="utf-8")

    result = bootstrap_workspace(tmp_path, profile="public", merge_guides=True)

    assert result["notes"]["root_claude_ignored"] is True
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "root claude\n"
    assert (tmp_path / ".claude" / "CLAUDE.md").is_file()


def test_bootstrap_guide_flags_conflict(tmp_path: Path) -> None:
    with pytest_raises_esaa("BOOTSTRAP_FLAGS_CONFLICT"):
        bootstrap_workspace(tmp_path, preserve_guides=True, merge_guides=True)


def test_bootstrap_merge_rejects_duplicate_markers() -> None:
    text = f"{GUIDE_MARKER_CONTRACT_BEGIN}\n{GUIDE_MARKER_CONTRACT_BEGIN}\n"

    with pytest_raises_esaa("BOOTSTRAP_MERGE_AMBIGUOUS"):
        validate_markers(text)


def test_bootstrap_merge_rejects_partial_markers() -> None:
    text = f"{GUIDE_MARKER_CONTRACT_BEGIN}\nbody\n{GUIDE_MARKER_CONTRACT_END}\n"

    with pytest_raises_esaa("BOOTSTRAP_MERGE_INVALID"):
        validate_markers(text)


def test_bootstrap_merge_invalid_guide_fails_before_governance_write(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(f"{GUIDE_MARKER_CONTRACT_BEGIN}\n", encoding="utf-8")

    with pytest_raises_esaa("BOOTSTRAP_MERGE_INVALID"):
        bootstrap_workspace(tmp_path, profile="public", merge_guides=True)

    assert not (tmp_path / ".roadmap" / "AGENT_CONTRACT.yaml").exists()


def test_bootstrap_cli_then_init_verify_and_eligible(tmp_path: Path) -> None:
    bootstrap_result = _run_cli(tmp_path, "bootstrap", "--profile", "public")
    assert bootstrap_result["status"] == "bootstrapped"

    init_result = _run_cli(tmp_path, "init")
    assert init_result["last_event_seq"] > 0
    assert init_result.get("task_source") == "empty"
    assert init_result.get("tasks_seeded") == []

    verify_result = _run_cli(tmp_path, "verify")
    assert verify_result["verify_status"] == "ok"

    eligible_result = _run_cli(tmp_path, "eligible")
    assert eligible_result["eligible_count"] == 0

    demo_init = _run_cli(tmp_path, "init", "--force", "--with-demo-tasks")
    assert demo_init.get("task_source") == "demo"
    assert "T-1000" in demo_init.get("tasks_seeded", [])
    eligible_demo = _run_cli(tmp_path, "eligible")
    assert eligible_demo["eligible_count"] >= 1


def test_package_data_contains_templates() -> None:
    template_root = resources.files("esaa").joinpath("templates")
    workspace_root = resources.files("esaa").joinpath("workspace")

    assert all(template_root.joinpath(name).is_file() for name in GOVERNANCE_TEMPLATE_FILES)
    assert all(workspace_root.joinpath(source).is_file() for source, _target in AGENT_GUIDE_TEMPLATE_FILES)


def test_packaged_governance_templates_match_canonical_files(repo_root: Path) -> None:
    template_root = repo_root / "src/esaa/templates"
    for name in ESSENTIAL_GOVERNANCE_FILES:
        assert (template_root / name).read_bytes() == (repo_root / ".roadmap" / name).read_bytes()


def test_packaged_agent_guides_match_canonical_files(repo_root: Path) -> None:
    workspace_root = repo_root / "src/esaa/workspace"
    assert "Contrato operacional ESAA" in (workspace_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Contrato operacional ESAA" in (workspace_root / "CLAUDE.md").read_text(encoding="utf-8")
    assert (workspace_root / "README.md").read_bytes() == (repo_root / "readme.md").read_bytes()


def test_pyproject_public_metadata(repo_root: Path) -> None:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert "version" not in project
    assert "version" in project.get("dynamic", [])
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "esaa.constants.PACKAGE_VERSION"
    assert project["license"] == "MIT"
    assert project["authors"] == [{"name": "ESAA Contributors"}]
    assert project["urls"]["Homepage"] == "https://github.com/elzobrito/ESAA---Event-Sourcing-Agent-Architecture"
    assert "build>=1.2.0" in project["optional-dependencies"]["dev"]
    assert "twine>=5.1.0" in project["optional-dependencies"]["dev"]


def test_public_version_surface(capsys) -> None:
    assert esaa.__version__ == PACKAGE_VERSION

    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"esaa {PACKAGE_VERSION}" in out
    assert "protocol 0.4.1" in out


def test_governance_bundle_versions_are_aligned(repo_root: Path) -> None:
    profiles = (
        ".roadmap/PARCER_PROFILE.agent-docs.yaml",
        ".roadmap/PARCER_PROFILE.agent-impl.yaml",
        ".roadmap/PARCER_PROFILE.agent-qa.yaml",
        ".roadmap/PARCER_PROFILE.agent-spec.yaml",
        ".roadmap/PARCER_PROFILE.orchestrator-runtime.yaml",
    )
    for rel in profiles:
        payload = yaml.safe_load((repo_root / rel).read_text(encoding="utf-8"))
        assert payload["parcer_profile"]["version"] == "0.4.1", rel

    storage = yaml.safe_load((repo_root / ".roadmap/STORAGE_POLICY.yaml").read_text(encoding="utf-8"))
    assert storage["version"] == "0.4.1"


def test_bootstrap_installed_console_smoke(tmp_path: Path, repo_root: Path) -> None:
    if not (repo_root / "dist").exists():
        return
    wheels = sorted((repo_root / "dist").glob(f"esaa_core-{PACKAGE_VERSION}-*.whl"))
    if not wheels:
        return

    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    esaa = venv_dir / ("Scripts/esaa.exe" if sys.platform == "win32" else "bin/esaa")
    subprocess.run([str(python), "-m", "pip", "install", "--force-reinstall", str(wheels[-1])], check=True)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run([str(esaa), "--root", str(workspace), "bootstrap", "--profile", "public"], check=True)
    assert (workspace / "AGENTS.md").is_file()
    assert (workspace / ".claude" / "CLAUDE.md").is_file()
    subprocess.run([str(esaa), "--root", str(workspace), "init"], check=True)
    verify = subprocess.run([str(esaa), "--root", str(workspace), "verify"], check=True, capture_output=True, text=True)
    assert '"verify_status": "ok"' in verify.stdout


class pytest_raises_esaa:
    def __init__(self, code: str) -> None:
        self.code = code

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert exc_type is ESAAError
        assert exc.code == self.code
        return True
