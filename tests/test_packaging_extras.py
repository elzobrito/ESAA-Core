from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import yaml

from esaa.cli import _build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_packaging_metadata_and_py_typed() -> None:
    assert (REPO_ROOT / "src" / "esaa" / "py.typed").is_file()

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.14" in classifiers

    package_data = pyproject["tool"]["setuptools"]["package-data"]["esaa"]
    assert "py.typed" in package_data
    assert "templates/*" in package_data
    assert "workspace/*" in package_data

    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    py_versions = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert "3.14" in py_versions


def test_demo_commands_marked_in_help() -> None:
    parser = _build_parser()
    top_help = parser.format_help()
    assert "[demo]" in top_help
    scenario_help = subprocess.run(
        [sys.executable, "-m", "esaa", "scenario", "--help"],
        cwd=str(REPO_ROOT / "src"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[demo]" in scenario_help.stdout

    claim_help = subprocess.run(
        [sys.executable, "-m", "esaa", "claim", "--help"],
        cwd=str(REPO_ROOT / "src"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[demo]" in claim_help.stdout


def test_wheel_contains_py_typed_templates_and_workspace(tmp_path: Path) -> None:
    outdir = tmp_path / "dist"
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    wheels = list(outdir.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())
    assert "esaa/py.typed" in names
    assert any(name.startswith("esaa/templates/") for name in names)
    assert any(name.startswith("esaa/workspace/") for name in names)
