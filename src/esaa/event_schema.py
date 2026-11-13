"""Append-only JSON Schema validation for ESAA activity events (ADR-0008 / AUD-O2-050)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from .constants import CANONICAL_ACTIONS
from .errors import ESAAError
from .reject_codes import EVENT_SCHEMA_INVALID

_SCHEMA_PATH = Path(__file__).resolve().parent / "templates" / "event.schema.json"


@lru_cache(maxsize=1)
def load_event_schema() -> dict[str, Any]:
    """Load and cache the canonical activity event JSON schema."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = load_event_schema()
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def list_covered_actions() -> tuple[str, ...]:
    """Return the actions that have explicit payload rules in event.schema.json."""
    schema = load_event_schema()
    actions: list[str] = []
    for clause in schema.get("allOf", []):
        const = clause.get("if", {}).get("properties", {}).get("action", {}).get("const")
        if isinstance(const, str):
            actions.append(const)
    return tuple(actions)


def validate_event_for_append(event: dict[str, Any]) -> None:
    """Validate an event strictly before appending it to activity.jsonl."""
    if not isinstance(event, dict):
        raise ESAAError(EVENT_SCHEMA_INVALID, "event.schema.json <root>: event must be a JSON object")

    action = event.get("action")
    if action not in CANONICAL_ACTIONS:
        raise ESAAError(
            EVENT_SCHEMA_INVALID,
            f"event.schema.json action={action!r} action: unsupported canonical action",
        )

    errors = sorted(
        _validator().iter_errors(event),
        key=lambda err: (len(list(err.absolute_path)), err.message),
        reverse=True,
    )
    if errors:
        err = errors[0]
        path = "/".join(str(part) for part in err.absolute_path) or "<root>"
        raise ESAAError(
            EVENT_SCHEMA_INVALID,
            f"event.schema.json action={action!r} {path}: {err.message}",
        )
