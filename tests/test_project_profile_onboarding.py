from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from esaa.bootstrap import bootstrap_workspace
from esaa.cli import main
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _answers(path: Path) -> Path:
    payload = {
        "operator_name": "Elzo",
        "workflow_preferences": {"guided_onboarding": True},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "AGENTS.md").write_text("project guide\n", encoding="utf-8")
    bootstrap_workspace(root, profile="production", preserve_guides=True)
    ESAAService(root).init(with_demo_tasks=True)
    return root


def test_onboard_requires_roadmap(tmp_path: Path) -> None:
    with pytest.raises(ESAAError) as exc:
        ESAAService(tmp_path).onboard({"project_name": "x"})
    assert exc.value.code == "ROADMAP_DIR_MISSING"


def test_onboard_dry_run_does_not_mutate_events_or_guides(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before_events = len(parse_event_store(root))
    before_guide = (root / "AGENTS.md").read_text(encoding="utf-8")

    result = _run_cli(root, "onboard", "--answers", str(_answers(tmp_path / "answers.json")), "--dry-run")

    assert result["status"] == "dry_run"
    assert result["project_profile"]["operator"]["display_name"] == "Elzo"
    assert result["project_profile"]["project_name"] == "workspace"
    assert result["tasks_created"] == ["GOV-PROFILE-001", "GOV-PROFILE-010", "GOV-PROFILE-020"]
    assert len(parse_event_store(root)) == before_events
    assert not (root / ".roadmap" / "project_profile.json").exists()
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == before_guide


def test_onboard_creates_profile_tasks_and_profile_show(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = _run_cli(root, "onboard", "--answers", str(_answers(tmp_path / "answers.json")))

    assert result["status"] == "accepted"
    assert result["tasks_created"] == ["GOV-PROFILE-001", "GOV-PROFILE-010", "GOV-PROFILE-020"]
    profile = _run_cli(root, "profile", "show")["project_profile"]
    assert profile["operator"]["display_name"] == "Elzo"
    assert profile["project_name"] == "workspace"
    assert "AGENTS.md" in profile["sources_of_truth"]
    assert ".roadmap/**" in profile["protected_paths"]
    assert profile["guide_topology"]["guides"][0]["path"] == "AGENTS.md"
    assert (root / ".roadmap" / "project_profile.json").exists()

    context = _run_cli(root, "dispatch-context", "GOV-PROFILE-001")
    assert context["project_profile"]["operator"]["display_name"] == "Elzo"
    assert context["project_profile"]["domain"] == "general-software"


def test_superseded_seed_is_hidden_from_eligible_but_state_keeps_audit(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _run_cli(root, "onboard", "--answers", str(_answers(tmp_path / "answers.json")))

    eligible = _run_cli(root, "eligible")
    ids = {task["task_id"] for task in eligible["eligible"]}
    assert "T-1000" not in ids
    assert "GOV-PROFILE-001" in ids
    assert eligible["suppressed_superseded_count"] == 3
    assert {task["task_id"] for task in eligible["suppressed_superseded"]} == {
        "T-1000",
        "T-1010",
        "T-1020",
    }

    state = _run_cli(root, "state", "T-1000")["task"]
    assert state["superseded_by"] == ["GOV-PROFILE-001"]


def test_esaa_core_gui_real_fixture_dry_run_if_present(tmp_path: Path) -> None:
    root = Path("/home/elzobrito/desenvolvimento/ESAA-Core-GUI")
    if not root.is_dir():
        pytest.skip("local ESAA-Core-GUI fixture is not present")

    verify = _run_cli(root, "verify")
    assert verify["verify_status"] == "ok"
    before_events = len(parse_event_store(root))

    result = _run_cli(root, "onboard", "--answers", str(_answers(tmp_path / "answers.json")), "--dry-run")

    assert result["status"] == "dry_run"
    assert len(parse_event_store(root)) == before_events
