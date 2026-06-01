from __future__ import annotations

from esaa.adapters.mock import MockAgentAdapter


def test_mock_adapter_uses_kind_safe_fallback_when_declared_outputs_are_logical() -> None:
    adapter = MockAgentAdapter()

    result = adapter.execute(
        {
            "task": {
                "task_id": "sso-client-default-T-002",
                "task_kind": "impl",
                "status": "in_progress",
                "outputs": {
                    "files": [
                        "docs/sso-clients/runtime-contract.json",
                        "runtime://sso_file_plan.all_in_one_client",
                    ]
                },
            }
        }
    )

    assert result["file_updates"][0]["path"] == "src/sso-client-default-t-002.txt"


def test_mock_adapter_skips_runtime_uri_for_qa_tasks() -> None:
    adapter = MockAgentAdapter()

    result = adapter.execute(
        {
            "task": {
                "task_id": "sso-client-default-T-006",
                "task_kind": "qa",
                "status": "in_progress",
                "outputs": {"files": ["runtime://sso_file_plan.tests"]},
            }
        }
    )

    assert result["file_updates"][0]["path"] == "docs/qa/sso-client-default-T-006.md"
