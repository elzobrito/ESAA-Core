"""Strict per-task resource limit resolution independent of persistence."""

from __future__ import annotations

from collections.abc import Mapping

_KEYS = frozenset({"max_file_updates", "max_bytes_per_update", "max_bytes_total"})
_MAX = 2**63 - 1


def _validate(values: Mapping[str, int], *, name: str, require_all: bool) -> dict[str, int]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be a mapping")
    unknown = set(values) - _KEYS
    if unknown or (require_all and set(values) != _KEYS):
        raise ValueError(f"{name} contains missing or unknown limit names")
    result = dict(values)
    for key, value in result.items():
        if type(value) is not int or not 1 <= value <= _MAX:
            raise ValueError(f"{name}.{key} must be a positive signed 64-bit integer")
    return result


def resolve_task_limits(
    defaults: Mapping[str, int],
    ceilings: Mapping[str, int] | None = None,
    requested: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Resolve explicit task limits under operator ceilings; absent caps equal defaults.

    The caller must use verified workspace policy and validate the returned limits
    at task creation and again against the locked task when submitting effects.
    This function does not change permissions, persist limits or allocate storage.
    """
    defaults = _validate(defaults, name="defaults", require_all=True)
    ceilings = _validate(ceilings if ceilings is not None else defaults, name="ceilings", require_all=True)
    requested = _validate(requested if requested is not None else {}, name="requested", require_all=False)
    if any(defaults[key] > ceilings[key] for key in _KEYS):
        raise ValueError("default limit exceeds administrative ceiling")
    result = defaults | requested
    if any(result[key] > ceilings[key] for key in _KEYS):
        raise ValueError("task limit exceeds administrative ceiling")
    return result
