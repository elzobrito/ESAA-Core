"""FIX-1812-QA — runner.metrics reserved action consistency."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from esaa.constants import CANONICAL_ACTIONS

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runner_metrics_in_canonical_actions():
    assert "runner.metrics" in CANONICAL_ACTIONS


def test_runner_metrics_in_agent_contract():
    p = REPO_ROOT / ".roadmap" / "AGENT_CONTRACT.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    reserved = data.get("vocabulary", {}).get("reserved_orchestrator_actions", [])
    assert "runner.metrics" in reserved, (
        f"runner.metrics missing from AGENT_CONTRACT.vocabulary.reserved_orchestrator_actions; "
        f"got: {reserved}"
    )


def test_runner_metrics_in_orchestrator_contract():
    p = REPO_ROOT / ".roadmap" / "ORCHESTRATOR_CONTRACT.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    reserved = data.get("roles", {}).get("orchestrator", {}).get("reserved_actions", [])
    assert "runner.metrics" in reserved, (
        f"runner.metrics missing from ORCHESTRATOR_CONTRACT.roles.orchestrator.reserved_actions; "
        f"got: {reserved}"
    )


def test_runner_metrics_not_in_allowed_agent_actions():
    p = REPO_ROOT / ".roadmap" / "AGENT_CONTRACT.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    allowed = data.get("vocabulary", {}).get("allowed_agent_actions", [])
    assert "runner.metrics" not in allowed


def test_runner_metrics_not_in_agent_result_schema_action_enum():
    p = REPO_ROOT / ".roadmap" / "agent_result.schema.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    enum = data["properties"]["activity_event"]["properties"]["action"]["enum"]
    assert "runner.metrics" not in enum
