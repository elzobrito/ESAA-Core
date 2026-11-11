"""FIX-1512 — Cobertura do MIN_CHECKS por task_kind (R8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.validator import validate_agent_output

ROOT = Path(__file__).resolve().parents[1]


def _load_schema():
    return json.loads((ROOT / ".roadmap/agent_result.schema.json").read_text(encoding="utf-8"))


def _load_contract():
    import yaml

    return yaml.safe_load((ROOT / ".roadmap/AGENT_CONTRACT.yaml").read_text(encoding="utf-8"))


def _complete(task_id, prior="in_progress", checks=None):
    ev = {"action": "complete", "task_id": task_id, "prior_status": prior}
    if checks is not None:
        ev["verification"] = {"checks": checks}
    return {"activity_event": ev, "file_updates": []}


def test_qa_complete_requires_at_least_one_check():
    schema, contract = _load_schema(), _load_contract()
    task = {
        "task_id": "Q-1",
        "task_kind": "qa",
        "status": "in_progress",
        "outputs": {"files": ["docs/qa/Q-1.md"]},
    }
    with pytest.raises(ESAAError) as exc:
        validate_agent_output(_complete("Q-1", checks=[]), schema, contract, task)
    # checks=[] viola schema (minItems 1) -> SCHEMA_INVALID, codigo curto
    assert exc.value.code in {"SCHEMA_INVALID", "MISSING_VERIFICATION"}


def test_spec_complete_requires_at_least_one_check():
    schema, contract = _load_schema(), _load_contract()
    task = {
        "task_id": "S-1",
        "task_kind": "spec",
        "status": "in_progress",
        "outputs": {"files": ["docs/spec/S-1.md"]},
    }
    # 1 check -> aceito; checks devem ser ao menos 1 por R8 (spec=1)
    ok = _complete("S-1", checks=["criterio enumerado"])
    ok["file_updates"] = [{"path": "docs/spec/S-1.md", "content": "x"}]
    event, files = validate_agent_output(ok, schema, contract, task)
    assert event["action"] == "complete"


def test_hotfix_complete_requires_two_checks():
    schema, contract = _load_schema(), _load_contract()
    task = {
        "task_id": "HF-X",
        "task_kind": "impl",
        "status": "in_progress",
        "is_hotfix": True,
        "issue_id": "ISS-1",
        "fixes": "ISS-1",
        "scope_patch": ["src/hotfix/"],
        "outputs": {"files": ["src/hotfix/HF-X.txt"]},
    }
    ev = {
        "activity_event": {
            "action": "complete",
            "task_id": "HF-X",
            "prior_status": "in_progress",
            "issue_id": "ISS-1",
            "fixes": "ISS-1",
            "verification": {"checks": ["unit-ok"]},
        },
        "file_updates": [{"path": "src/hotfix/HF-X.txt", "content": "x"}],
    }
    with pytest.raises(ESAAError) as exc:
        validate_agent_output(ev, schema, contract, task)
    assert exc.value.code == "MISSING_VERIFICATION"
