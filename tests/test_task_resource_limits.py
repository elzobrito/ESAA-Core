import pytest

from esaa.task_resource_limits import resolve_task_limits

DEFAULTS = {"max_file_updates": 32, "max_bytes_per_update": 2097152, "max_bytes_total": 8388608}
CEILINGS = {"max_file_updates": 64, "max_bytes_per_update": 4294967296, "max_bytes_total": 8589934592}


def test_defaults_and_explicit_values():
    assert resolve_task_limits(DEFAULTS) == DEFAULTS
    assert resolve_task_limits(DEFAULTS, CEILINGS, {"max_bytes_per_update": 4294967296}) == {
        **DEFAULTS,
        "max_bytes_per_update": 4294967296,
    }
    assert resolve_task_limits(DEFAULTS, CEILINGS, {"max_file_updates": 1})["max_file_updates"] == 1
    assert DEFAULTS["max_file_updates"] == 32


def test_no_elevated_ceiling_means_no_increase():
    with pytest.raises(ValueError, match="ceiling"):
        resolve_task_limits(DEFAULTS, requested={"max_bytes_per_update": 2097153})


@pytest.mark.parametrize("value", [True, False, 0, -1, "42", 1.5, 2**63])
def test_reject_invalid_values(value):
    with pytest.raises(ValueError):
        resolve_task_limits(DEFAULTS, CEILINGS, {"max_bytes_per_update": value})


def test_reject_unknown_and_inconsistent_policy():
    with pytest.raises(ValueError):
        resolve_task_limits(DEFAULTS, CEILINGS, {"unknown": 1})
    with pytest.raises(ValueError):
        resolve_task_limits(DEFAULTS, {"max_file_updates": 2})
    with pytest.raises(ValueError):
        resolve_task_limits(DEFAULTS, {**CEILINGS, "max_file_updates": 1})
