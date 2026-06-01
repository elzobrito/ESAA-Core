"""ESAA core package."""

from importlib.metadata import PackageNotFoundError, version

from .constants import ESAA_VERSION, PACKAGE_VERSION, SCHEMA_VERSION


def _package_version() -> str:
    try:
        return version("esaa-core")
    except PackageNotFoundError:
        return PACKAGE_VERSION


__version__ = _package_version()

__all__ = ["SCHEMA_VERSION", "ESAA_VERSION", "PACKAGE_VERSION", "__version__"]
