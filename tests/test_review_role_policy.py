"""FIX-1807-QA — Independent QA review role policy."""
from __future__ import annotations

from pathlib import Path
import yaml

import pytest

from esaa.errors import ESAAError
from esaa.runtime_policy import resolve_role, review_authorization_mode
from esaa.service import ESAAService


def test_resolve_role_heuristic_qa() -> None:
    assert resolve_role("agent-qa") == "qa"
    assert resolve_role("agent-qa-v2") == "qa"


def test_resolve_role_heuristic_orchestrator() -> None:
    assert resolve_role("orchestrator") == "orchestrator"
    assert resolve_role("agent-orchestrator") == "orchestrator"


def test_resolve_role_default_agent() -> None:
    assert resolve_role("agent-spec") == "agent"
    assert resolve_role("agent-impl") == "agent"


def test_resolve_role_from_swarm_yaml(tmp_path: Path) -> None:
    (tmp_path / ".roadmap").mkdir()
    (tmp_path / ".roadmap" / "agents_swarm.yaml").write_text(
        yaml.safe_dump({"agents": {"alice": {"role": "qa"}}}),
        encoding="utf-8",
    )
    assert resolve_role("alice", root=tmp_path) == "qa"
    assert resolve_role("bob", root=tmp_path) == "agent"  # fallback heurístico


def test_review_authorization_mode_default_owner() -> None:
    assert review_authorization_mode({}) == "owner"
    assert review_authorization_mode({"review_authorization": "owner"}) == "owner"


def test_review_authorization_mode_qa_role() -> None:
    assert review_authorization_mode({"review_authorization": "qa_role"}) == "qa_role"


def test_review_authorization_mode_invalid_falls_back() -> None:
    assert review_authorization_mode({"review_authorization": "weird"}) == "owner"


def _setup_qa_role_policy(contract_bundle: Path) -> None:
    rp = contract_bundle / ".roadmap" / "RUNTIME_POLICY.yaml"
    data = yaml.safe_load(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    data["review_authorization"] = "qa_role"
    rp.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_owner_review_rejected_when_qa_role(contract_bundle: Path) -> None:
    """Sob qa_role: owner (agent-spec) tenta review -> REVIEW_ROLE_VIOLATION."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _setup_qa_role_policy(contract_bundle)
    # Invalida cache de policy
    svc._policy_cache = None

    svc.submit({"activity_event": {
        "action": "claim", "task_id": "T-1000", "prior_status": "todo"
    }}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "complete", "task_id": "T-1000", "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor="agent-spec")

    with pytest.raises(ESAAError) as exc:
        svc.submit({"activity_event": {
            "action": "review", "task_id": "T-1000", "prior_status": "review",
            "decision": "approve", "tasks": ["T-1000"],
        }}, actor="agent-spec")
    assert exc.value.code == "REVIEW_ROLE_VIOLATION"


def test_qa_actor_can_review_when_qa_role(contract_bundle: Path) -> None:
    """Sob qa_role: agent-qa pode reviewar mesmo nao tendo feito claim."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    _setup_qa_role_policy(contract_bundle)
    svc._policy_cache = None

    svc.submit({"activity_event": {
        "action": "claim", "task_id": "T-1000", "prior_status": "todo"
    }}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "complete", "task_id": "T-1000", "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor="agent-spec")

    # agent-qa faz review (nao foi o owner)
    r = svc.submit({"activity_event": {
        "action": "review", "task_id": "T-1000", "prior_status": "review",
        "decision": "approve", "tasks": ["T-1000"],
    }}, actor="agent-qa")
    assert r["status"] == "accepted"


def test_default_owner_mode_backward_compat(contract_bundle: Path) -> None:
    """Sem policy explicita: owner pode reviewar (legado)."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)

    svc.submit({"activity_event": {
        "action": "claim", "task_id": "T-1000", "prior_status": "todo"
    }}, actor="agent-spec")
    svc.submit({"activity_event": {
        "action": "complete", "task_id": "T-1000", "prior_status": "in_progress",
        "verification": {"checks": ["ok"]},
    }, "file_updates": [{"path": "docs/spec/T-1000.md", "content": "#\n"}]}, actor="agent-spec")
    r = svc.submit({"activity_event": {
        "action": "review", "task_id": "T-1000", "prior_status": "review",
        "decision": "approve", "tasks": ["T-1000"],
    }}, actor="agent-spec")
    assert r["status"] == "accepted"
