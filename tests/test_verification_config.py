import copy
import json

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store
from esaa.verification_config import normalize_config

IMAGE = "alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
CONFIG = {
    "checks": [
        {
            "id": "unit",
            "image": IMAGE,
            "command": ["/bin/sh", "-c", "test -f tetris.py"],
            "inputs": ["tetris.py"],
        }
    ]
}


def enabled(root):
    svc = ESAAService(root)
    svc.init()
    (root / ".roadmap/RUNTIME_POLICY.yaml").write_text("review_authorization: qa_role\n")
    svc.verification_enable(CONFIG)
    return svc


def test_enable_dry_run_and_custom_schema(contract_bundle):
    s = ESAAService(contract_bundle)
    s.init()
    before = {str(p): p.read_bytes() for p in contract_bundle.rglob("*") if p.is_file()}
    result = s.verification_enable(CONFIG, dry_run=True)
    assert result["status"] == "dry_run"
    assert before == {str(p): p.read_bytes() for p in contract_bundle.rglob("*") if p.is_file()}
    p = contract_bundle / ".roadmap/agent_result.schema.json"
    schema = json.loads(p.read_text())
    schema["description"] = "custom preserved"
    p.write_text(json.dumps(schema))
    s.verification_enable(CONFIG)
    assert json.loads(p.read_text())["description"] == "custom preserved"
    assert s.verification_show()["config"]["checks"][0]["timeout_seconds"] == 60
    s.create_task("T-C", task_kind="impl", title="candidate", executable_checks=["unit"])
    assert s.task_state("T-C")["task"]["executable_checks"] == ["unit"]
    assert s.verify()["verify_status"] == "ok"
    assert any(e["schema_version"] == "0.4.2" for e in parse_event_store(contract_bundle))
    with pytest.raises(ESAAError):
        s.amend_task("T-C", executable_checks=["unknown"])


@pytest.mark.parametrize(
    "mutation",
    [
        {"image": "alpine:latest"},
        {"command": "echo x"},
        {"inputs": ["../secret"]},
        {"inputs": [".roadmap/**"]},
        {"timeout_seconds": 0},
        {"env": {"TOKEN": "secret"}},
        {"cpus": True},
    ],
)
def test_reject_config(mutation):
    config = copy.deepcopy(CONFIG)
    config["checks"][0].update(mutation)
    with pytest.raises(ESAAError):
        normalize_config(config)


def test_incompatible_custom_schema_and_grants_not_from_agent(contract_bundle):
    s = ESAAService(contract_bundle)
    s.init()
    p = contract_bundle / ".roadmap/agent_result.schema.json"
    schema = json.loads(p.read_text())
    schema["properties"]["activity_event"]["properties"]["verification"]["properties"]["execution_id"] = {
        "type": "integer"
    }
    p.write_text(json.dumps(schema))
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
    with pytest.raises(ESAAError, match="incompatible"):
        s.verification_enable(CONFIG)
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
    with pytest.raises(ESAAError):
        s.create_task("T-C", task_kind="impl", title="x", executable_checks=["unit"])


def test_schema_effects_commit_under_store_lock(contract_bundle, monkeypatch):
    import esaa.verification_service as module

    s = ESAAService(contract_bundle)
    s.init()
    original = module.commit_staged
    calls = []

    def checked(root, staged):
        assert (root / ".roadmap/activity.jsonl.lock").exists()
        calls.append(True)
        original(root, staged)

    monkeypatch.setattr(module, "commit_staged", checked)
    s.verification_enable(CONFIG)
    assert calls and s.verify()["verify_status"] == "ok"
