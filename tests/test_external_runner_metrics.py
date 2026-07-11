from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

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


def test_external_runner_metrics_are_recorded_and_aggregated(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    result = service.record_runner_metrics(
        {
            "task_id": "T-1000",
            "actor": "agent-external",
            "runner_id": "codex-desktop-1",
            "runner_kind": "codex",
            "model": "gpt-5",
            "command_surface": "python -m esaa",
            "started_at": "2026-05-23T10:00:00Z",
            "ended_at": "2026-05-23T10:00:02.500Z",
            "input_tokens": 120,
            "output_tokens": 80,
            "status": "success",
            "correlation_id": "CID-CMM5",
        }
    )

    assert result["action"] == "runner.metrics"
    assert result["verify_status"] == "ok"
    metrics = service.metrics()
    assert metrics["events_by_action"]["runner.metrics"] == 1
    assert metrics["runner"]["events"] == 1
    assert metrics["runner"]["latency_ms_total"] == 2500
    assert metrics["runner"]["tokens_total"] == 200
    assert metrics["runner"]["by_runner_kind"] == {"codex": 1}
    assert metrics["runner"]["by_model"] == {"gpt-5": 1}
    assert metrics["runner"]["by_status"] == {"success": 1}
    assert service.verify()["verify_status"] == "ok"


def test_external_runner_metrics_preserve_unknown_values_and_errors(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    service.record_runner_metrics(
        {
            "task_id": "T-1000",
            "actor": "agent-external",
            "runner_id": "claude-code-1",
            "runner_kind": "claude-code",
            "model": None,
            "command_surface": "esaa run",
            "latency_ms": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "status": "failed",
            "error_code": "ADAPTER_EXITED",
        }
    )

    event = parse_event_store(contract_bundle)[-3]
    assert event["action"] == "runner.metrics"
    assert event["payload"]["model"] is None
    assert event["payload"]["latency_ms"] is None
    metrics = service.metrics()
    assert metrics["runner"]["tokens_total"] == 0
    assert metrics["runner"]["latency_ms_total"] == 0
    assert metrics["runner"]["errors_by_code"] == {"ADAPTER_EXITED": 1}


def test_runner_metrics_reject_invalid_payload(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    with pytest.raises(ESAAError) as excinfo:
        service.record_runner_metrics(
            {
                "task_id": "T-1000",
                "actor": "agent-external",
                "runner_id": "bad",
                "runner_kind": "codex",
                "command_surface": "esaa run",
                "latency_ms": -1,
                "status": "success",
            }
        )

    assert excinfo.value.code == "SCHEMA_INVALID"


def test_runner_metrics_cli_records_payload_file(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True, with_demo_tasks=True)
    payload = contract_bundle / "runner-metrics.json"
    payload.write_text(
        json.dumps(
            {
                "task_id": "T-1000",
                "actor": "agent-external",
                "runner_id": "antigravity-1",
                "runner_kind": "antigravity",
                "model": "unknown",
                "command_surface": "cmd.exe",
                "latency_ms": 15,
                "input_tokens": 1,
                "output_tokens": 2,
                "status": "success",
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(contract_bundle, "runner", "metrics", "--file", str(payload))

    assert result["action"] == "runner.metrics"
    assert result["verify_status"] == "ok"

