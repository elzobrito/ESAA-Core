import tomllib
from pathlib import Path

import yaml


def _config():
    root = Path(__file__).resolve().parents[1]
    return yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8")), tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )


def _commands(job):
    return [step["run"] for step in job["steps"] if "run" in step]


def test_full_lint_and_format_scope():
    ci, project = _config()
    assert "ruff check src tests" in _commands(ci["jobs"]["lint"])
    assert "black --check src tests" in _commands(ci["jobs"]["lint"])
    assert project["tool"]["black"]["target-version"] == ["py311"]
    assert project["tool"]["ruff"]["target-version"] == "py311"


def test_typecheck_blocks_ci():
    ci, _ = _config()
    job = ci["jobs"]["typecheck"]
    assert not job.get("continue-on-error", False)
    assert "mypy src/esaa" in _commands(job)
    assert not any(step.get("continue-on-error", False) for step in job["steps"])


def test_linux_and_windows_python_matrix():
    ci, _ = _config()
    job = ci["jobs"]["test"]
    assert job["runs-on"] == "${{ matrix.os }}"
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert set(job["strategy"]["matrix"]["python-version"]) == {"3.11", "3.12", "3.13"}


def test_coverage_gate_and_dependency_audit():
    ci, project = _config()
    command = next(c for c in _commands(ci["jobs"]["coverage"]) if "--cov=esaa" in c)
    assert "--cov-report=xml" in command
    assert float(command.split("--cov-fail-under=")[1].split()[0]) > 0
    assert "python -m pip_audit --strict ." in _commands(ci["jobs"]["audit"])
    assert any(d.startswith("pytest-cov") for d in project["project"]["optional-dependencies"]["dev"])
