"""Consumer guidance must work without the ESAA-Core checkout or its docs tree."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from esaa.bootstrap import GOVERNANCE_TEMPLATE_FILES, bootstrap_workspace

REPO = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)


def assert_local_links_exist(root: Path, path: Path) -> None:
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("#"):
            continue
        dest = (path.parent / target.split("#", 1)[0]).resolve()
        assert dest.is_relative_to(root.resolve()), (path, target)
        assert dest.is_file(), (path, target)


@pytest.mark.parametrize("profile", ["public", "production"])
@pytest.mark.parametrize("mode", ["default", "preserve", "merge", "overwrite"])
def test_consumer_links_and_project_content(tmp_path: Path, profile: str, mode: str) -> None:
    sentinel = "Local project instructions: retain this exact sentence.\n"
    if mode != "default":
        bootstrap_workspace(tmp_path, profile=profile)
        for rel in ("AGENTS.md", "README.md", ".claude/CLAUDE.md"):
            path = tmp_path / rel
            path.write_text(path.read_text(encoding="utf-8") + "\n" + sentinel, encoding="utf-8")
    kwargs = {"force": True} if mode != "default" else {}
    if mode == "preserve":
        kwargs["preserve_guides"] = True
    if mode == "merge":
        kwargs["merge_guides"] = True
    bootstrap_workspace(tmp_path, profile=profile, **kwargs)
    assert not (tmp_path / "docs").exists()
    for rel in ("AGENTS.md", "README.md", ".claude/CLAUDE.md"):
        path = tmp_path / rel
        assert_local_links_exist(tmp_path, path)
        assert (sentinel in path.read_text(encoding="utf-8")) == (mode in {"preserve", "merge"})
    if mode == "merge":
        # Refresh repeatedly, preserving the project region and valid routing.
        bootstrap_workspace(tmp_path, profile=profile, force=True, merge_guides=True)
        for rel in ("AGENTS.md", "README.md", ".claude/CLAUDE.md"):
            path = tmp_path / rel
            assert path.read_text(encoding="utf-8").count(sentinel) == 1
            assert_local_links_exist(tmp_path, path)


def test_contract_change_is_narrative_only() -> None:
    active = yaml.safe_load((REPO / ".roadmap/AGENT_CONTRACT.yaml").read_text())
    packaged = yaml.safe_load((REPO / "src/esaa/templates/AGENT_CONTRACT.yaml").read_text())
    # Only this exact descriptive leaf may differ; permissions/defaults/gates may not.
    active["dispatch_model"].pop("description")
    packaged["dispatch_model"].pop("description")
    assert packaged == active


@pytest.mark.parametrize("name", [n for n in GOVERNANCE_TEMPLATE_FILES if n.startswith("PARCER_PROFILE.")])
def test_profile_identity_and_top_level_compatibility(name: str) -> None:
    active = yaml.safe_load((REPO / ".roadmap" / name).read_text())
    packaged = yaml.safe_load((REPO / "src/esaa/templates" / name).read_text())
    assert set(packaged) == set(active)
    assert packaged["parcer_profile"] == active["parcer_profile"]
    role_key = "persona" if "persona" in active else "agent_profile" if "agent_profile" in active else "runtime_actor"
    assert packaged[role_key]["role"]


def test_bilingual_runner_examples_are_identical_and_valid() -> None:
    pt = (REPO / "docs/guides/esaa-runners-codex-claude-code.md").read_text()
    en = (REPO / "docs/guides/esaa-runners-codex-claude-code.en.md").read_text()
    assert FENCE.findall(pt) == FENCE.findall(en)
    schema = json.loads((REPO / "src/esaa/templates/agent_result.schema.json").read_text())
    for language, body in FENCE.findall(pt):
        if language != "json":
            continue
        payload = json.loads(body)
        if "activity_event" in payload:
            jsonschema.validate(payload, schema)
        else:
            jsonschema.validate(payload, schema["properties"]["file_updates"]["items"])


def test_bilingual_runtime_supplement_examples_are_identical() -> None:
    pt = (REPO / "docs/guides/esaa-cli-reference.md").read_text().split("## Arquitetura e operações do runtime\n", 1)[1]
    en = (REPO / "docs/guides/esaa-cli-reference.en.md").read_text().split("## Runtime architecture and operations\n", 1)[1]
    assert FENCE.findall(pt) == FENCE.findall(en)
