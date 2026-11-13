from __future__ import annotations

import re
from pathlib import Path

from esaa.bootstrap import bootstrap_workspace
from esaa.constants import PACKAGE_VERSION
from esaa.service import ESAAService

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_changelog_first_version_matches_package_version() -> None:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s+([^\s]+)", changelog, flags=re.MULTILINE)
    assert match is not None
    assert match.group(1) == PACKAGE_VERSION


def test_upgrade_from_published_b25_fixture_cycle(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests" / "fixtures" / "logs" / "v0.5.0b25" / "activity.jsonl"
    assert fixture.is_file()

    bootstrap_workspace(tmp_path)
    (tmp_path / ".roadmap" / "activity.jsonl").write_text(
        fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )
    svc = ESAAService(tmp_path)
    svc.project()
    assert svc.verify()["verify_status"] == "ok"

    svc.create_task("UPG-001", "impl", "Upgrade smoke", outputs=["src/upg.txt"])
    svc.claim_task("UPG-001", actor="agent-impl")
    svc.complete_task("UPG-001", actor="agent-impl", checks=["ok"])
    svc.review_task("UPG-001", actor="agent-qa", decision="approve")
    assert svc.verify()["verify_status"] == "ok"
