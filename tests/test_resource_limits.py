from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from esaa.adapters import http_llm
from esaa.adapters.http_llm import HttpLlmAdapter
from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.store import parse_event_store
from esaa.validator import validate_file_update_resource_limits


def _set_resource_limits(root: Path, **limits: int) -> None:
    policy_path = root / ".roadmap" / "RUNTIME_POLICY.yaml"
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    data["resource_limits"] = limits
    policy_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _claim_spec_task(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    return svc


def _complete_with_updates(updates: list[dict[str, str]]) -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": "T-1000",
            "prior_status": "in_progress",
            "verification": {"checks": ["limited"]},
        },
        "file_updates": updates,
    }


def test_file_update_count_limit_rejects_before_staging_and_append(contract_bundle: Path) -> None:
    _set_resource_limits(
        contract_bundle,
        max_file_updates=1,
        max_bytes_per_update=100,
        max_bytes_total=100,
    )
    svc = _claim_spec_task(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as excinfo:
        svc.submit(
            _complete_with_updates([
                {"path": "docs/spec/a.md", "content": "a"},
                {"path": "docs/spec/b.md", "content": "b"},
            ]),
            actor="agent-spec",
        )

    assert excinfo.value.code == "RESOURCE_LIMIT_EXCEEDED"
    assert len(parse_event_store(contract_bundle)) == before
    staging = contract_bundle / ".roadmap" / "staging"
    assert not staging.exists() or not any(staging.rglob("*"))


def test_file_update_byte_limits_cover_per_update_and_total() -> None:
    with pytest.raises(ESAAError) as per_update:
        validate_file_update_resource_limits(
            [{"path": "docs/spec/a.md", "content": "abcd"}],
            {"resource_limits": {"max_file_updates": 3, "max_bytes_per_update": 3, "max_bytes_total": 100}},
        )
    assert per_update.value.code == "RESOURCE_LIMIT_EXCEEDED"

    with pytest.raises(ESAAError) as total:
        validate_file_update_resource_limits(
            [
                {"path": "docs/spec/a.md", "content": "abc"},
                {"path": "docs/spec/b.md", "content": "def"},
            ],
            {"resource_limits": {"max_file_updates": 3, "max_bytes_per_update": 10, "max_bytes_total": 5}},
        )
    assert total.value.code == "RESOURCE_LIMIT_EXCEEDED"


def test_http_adapter_rejects_response_above_byte_limit() -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size: int) -> bytes:
            return b'{"agent_result":{"activity_event":{}}}'

    def fake_urlopen(*args, **kwargs):
        return FakeResponse()

    original = http_llm.urllib.request.urlopen
    http_llm.urllib.request.urlopen = fake_urlopen
    try:
        with pytest.raises(ESAAError) as excinfo:
            HttpLlmAdapter("http://example.invalid", max_response_bytes=4).execute({"task": "T"})
    finally:
        http_llm.urllib.request.urlopen = original

    assert excinfo.value.code == "RESOURCE_LIMIT_EXCEEDED"
