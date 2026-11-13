from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from esaa.trust_root import ENV_TRUST_ROOT


@pytest.fixture(autouse=True)
def _isolate_trust_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ENV_TRUST_ROOT, raising=False)
    monkeypatch.setattr(
        "esaa.trust_enrollment.registry_directory",
        lambda: tmp_path.parent / ("owner-enrollments-" + tmp_path.name),
    )


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def live_identity_pin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo_root: Path) -> Path:
    """Bind a disposable owner pin so tests can parse the identity-active live store."""
    from esaa.identity import load_anchor
    from esaa.trust_root import import_trust_pin, make_pin

    if not (repo_root / ".roadmap" / "governance-anchor.json").is_file():
        pytest.skip("live store has no governance-anchor.json")
    trust = tmp_path / "live-trust-root"
    trust.mkdir()
    monkeypatch.setenv(ENV_TRUST_ROOT, str(trust))
    anchor = load_anchor(repo_root)
    import_trust_pin(repo_root, make_pin(public_key_hex=anchor["public_key_hex"]))
    return repo_root


@pytest.fixture
def contract_bundle(tmp_path: Path, repo_root: Path) -> Path:
    source = repo_root / ".roadmap"
    target = tmp_path / ".roadmap"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("AGENT_CONTRACT.yaml", "agent_result.schema.json", "roadmap.schema.json"):
        shutil.copy2(source / name, target / name)
    return tmp_path
