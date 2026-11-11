from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .errors import ESAAError

REQUIRED_FIELDS = ("task_id", "actor", "runner_id", "runner_kind", "command_surface", "status")
STATUS_VALUES = {"success", "failed", "cancelled", "unknown"}


def _parse_ts(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ESAAError("SCHEMA_INVALID", f"{field} must be an ISO-8601 string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ESAAError("SCHEMA_INVALID", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_non_negative_int(payload: dict[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ESAAError("SCHEMA_INVALID", f"{field} must be an integer or null")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ESAAError("SCHEMA_INVALID", f"{field} must be an integer or null") from exc
    if parsed < 0:
        raise ESAAError("SCHEMA_INVALID", f"{field} must be >= 0")
    return parsed


def _optional_non_negative_float(payload: dict[str, Any], field: str) -> float | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ESAAError("SCHEMA_INVALID", f"{field} must be a number or null")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ESAAError("SCHEMA_INVALID", f"{field} must be a number or null") from exc
    if parsed < 0:
        raise ESAAError("SCHEMA_INVALID", f"{field} must be >= 0")
    return parsed


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ESAAError("SCHEMA_INVALID", f"{field} is required")
    return value.strip()


def normalize_runner_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    for field in REQUIRED_FIELDS:
        if field not in payload:
            raise ESAAError("SCHEMA_INVALID", f"{field} is required")

    status = _required_str(payload, "status")
    if status not in STATUS_VALUES:
        raise ESAAError("SCHEMA_INVALID", f"status must be one of {sorted(STATUS_VALUES)}")

    started = _parse_ts(payload.get("started_at"), "started_at")
    ended = _parse_ts(payload.get("ended_at"), "ended_at")
    latency_ms = _optional_non_negative_int(payload, "latency_ms")
    if latency_ms is None and started and ended:
        delta_ms = int((ended - started).total_seconds() * 1000)
        if delta_ms < 0:
            raise ESAAError("SCHEMA_INVALID", "ended_at must be >= started_at")
        latency_ms = delta_ms

    input_tokens = _optional_non_negative_int(payload, "input_tokens")
    output_tokens = _optional_non_negative_int(payload, "output_tokens")
    total_tokens = _optional_non_negative_int(payload, "total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    out = {
        "task_id": _required_str(payload, "task_id"),
        "actor": _required_str(payload, "actor"),
        "runner_id": _required_str(payload, "runner_id"),
        "runner_kind": _required_str(payload, "runner_kind"),
        "model": payload.get("model"),
        "command_surface": _required_str(payload, "command_surface"),
        "started_at": payload.get("started_at"),
        "ended_at": payload.get("ended_at"),
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_estimate": _optional_non_negative_float(payload, "cost_estimate"),
        "status": status,
        "error_code": payload.get("error_code"),
        "correlation_id": payload.get("correlation_id"),
    }

    if out["model"] is not None and not isinstance(out["model"], str):
        raise ESAAError("SCHEMA_INVALID", "model must be a string or null")
    if out["error_code"] is not None and not isinstance(out["error_code"], str):
        raise ESAAError("SCHEMA_INVALID", "error_code must be a string or null")
    if out["correlation_id"] is not None and not isinstance(out["correlation_id"], str):
        raise ESAAError("SCHEMA_INVALID", "correlation_id must be a string or null")
    return out
