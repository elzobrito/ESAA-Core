from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .constants import PROTOCOL_VERSION, SCHEMA_VERSION
from .errors import CorruptedStoreError
from .reject_codes import UNSUPPORTED_EVENT_SCHEMA_VERSION

UpcasterFn = Callable[[dict[str, Any]], dict[str, Any]]


def _upcast_0_3_to_0_4(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize v0.3-style events into canonical v0.4.0 shape without mutating input."""
    event = deepcopy(raw)
    if "payload" not in event and "data" in event:
        event["payload"] = event.pop("data")
    elif "data" in event:
        event.pop("data")

    if event.get("action") == "run.init":
        event["action"] = "run.start"
        payload = event.setdefault("payload", {})
        if isinstance(payload, dict):
            payload.setdefault("status", "initialized")

    event["schema_version"] = "0.4.0"
    return event


def _upcast_0_4_0_to_0_4_1(raw: dict[str, Any]) -> dict[str, Any]:
    """Identity upcast from 0.4.0 to 0.4.1."""
    event = deepcopy(raw)
    event["schema_version"] = "0.4.1"
    return event


def _upcast_0_4_1_to_0_4_2(raw: dict[str, Any]) -> dict[str, Any]:
    """Upcast 0.4.1 to 0.4.2 without inventing projection_hash_after."""
    event = deepcopy(raw)
    event["schema_version"] = "0.4.2"
    return event


# Ordered registry: source_version -> (next_version, pure_upcaster)
UPCASTERS: dict[str, tuple[str, UpcasterFn]] = {
    "0.3.0": ("0.4.0", _upcast_0_3_to_0_4),
    "0.4.0": ("0.4.1", _upcast_0_4_0_to_0_4_1),
    "0.4.1": ("0.4.2", _upcast_0_4_1_to_0_4_2),
}


def upcast_event(
    raw: dict[str, Any],
    *,
    target_version: str = SCHEMA_VERSION,
    registry: dict[str, tuple[str, UpcasterFn]] | None = None,
) -> dict[str, Any]:
    """Apply the ordered upcaster chain from raw's schema_version up to target_version."""
    chain = registry if registry is not None else UPCASTERS
    event = deepcopy(raw)
    if "payload" not in event and "data" in event:
        event["payload"] = event.pop("data")
    version = event.get("schema_version")
    if version is None:
        version = "0.3.0"
    if not isinstance(version, str) or not version:
        raise CorruptedStoreError(
            UNSUPPORTED_EVENT_SCHEMA_VERSION,
            f"invalid schema_version: {version!r}",
        )

    if registry is None and target_version == SCHEMA_VERSION and version == PROTOCOL_VERSION:
        return event

    visited: set[str] = set()
    while version != target_version:
        if version in visited:
            raise CorruptedStoreError(
                UNSUPPORTED_EVENT_SCHEMA_VERSION,
                f"upcaster cycle detected at schema_version={version}",
            )
        visited.add(version)
        step = chain.get(version)
        if step is None:
            raise CorruptedStoreError(
                UNSUPPORTED_EVENT_SCHEMA_VERSION,
                f"no upcaster route from schema_version={version} to {target_version}",
            )
        next_version, upcaster = step
        event = upcaster(event)
        event["schema_version"] = next_version
        version = next_version

    return event


def normalize_legacy_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy events up to the current storage schema_version."""
    return upcast_event(raw, target_version=SCHEMA_VERSION)


def normalize_legacy_verify_status(status: str) -> str:
    if status == "fail":
        return "mismatch"
    return status
