"""QUA-02: constants.PACKAGE_VERSION e a fonte unica de versao do pacote."""
from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover - ambiente legado
    import tomli as tomllib  # type: ignore[no-redef]

from esaa.constants import PACKAGE_VERSION


def _pyproject(repo_root: Path) -> dict:
    return tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_has_no_literal_version(repo_root: Path) -> None:
    data = _pyproject(repo_root)
    assert "version" not in data["project"], "versao literal no pyproject duplica constants.PACKAGE_VERSION"
    assert "version" in data["project"].get("dynamic", [])


def test_dynamic_version_points_to_constants(repo_root: Path) -> None:
    data = _pyproject(repo_root)
    attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "esaa.constants.PACKAGE_VERSION"


def test_package_dunder_version_matches_constants() -> None:
    import esaa

    assert esaa.__version__ == PACKAGE_VERSION


def test_version_format_is_pep440_like() -> None:
    assert PACKAGE_VERSION and PACKAGE_VERSION[0].isdigit()
