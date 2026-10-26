from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from esaa.trust_root import ENV_TRUST_ROOT


@pytest.fixture(autouse=True)
def _isolate_trust_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ENV_TRUST_ROOT, raising=False)
    monkeypatch.setattr("esaa.trust_enrollment.registry_directory", lambda: tmp_path.parent / ("owner-enrollments-" + tmp_path.name))


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def contract_bundle(tmp_path: Path, repo_root: Path) -> Path:
    source = repo_root / ".roadmap"
    target = tmp_path / ".roadmap"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("AGENT_CONTRACT.yaml", "agent_result.schema.json", "roadmap.schema.json"):
        shutil.copy2(source / name, target / name)
    return tmp_path
