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

MINIMAL_AGENT_GUIDANCE = "O ESAA não usa MCP.\nUse a CLI ESAA: python -m esaa.\n"


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
    assert agents == MINIMAL_AGENT_GUIDANCE
    assert claude == MINIMAL_AGENT_GUIDANCE
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


def test_bootstrap_cli_then_init_verify_and_eligible(tmp_path: Path) -> None:
    bootstrap_result = _run_cli(tmp_path, "bootstrap", "--profile", "public")
    assert bootstrap_result["status"] == "bootstrapped"

    init_result = _run_cli(tmp_path, "init")
    assert init_result["last_event_seq"] > 0

    verify_result = _run_cli(tmp_path, "verify")
    assert verify_result["verify_status"] == "ok"

    eligible_result = _run_cli(tmp_path, "eligible")
    assert eligible_result["eligible_count"] >= 1


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
    assert (workspace_root / "AGENTS.md").read_text(encoding="utf-8") == MINIMAL_AGENT_GUIDANCE
    assert (workspace_root / "CLAUDE.md").read_text(encoding="utf-8") == MINIMAL_AGENT_GUIDANCE
    assert (workspace_root / "README.md").read_bytes() == (repo_root / "readme.md").read_bytes()


def test_pyproject_public_metadata(repo_root: Path) -> None:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert project["version"] == PACKAGE_VERSION
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
