from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .utils import normalize_rel_path


def normalize_write_set(paths: Iterable[str]) -> list[str]:
    out = []
    for path in paths:
        norm = normalize_rel_path(path).strip()
        if not norm:
            continue
        out.append(norm)
    return sorted(set(out))


def _is_dir(path: str) -> bool:
    return path.endswith("/")


def _is_prefix_conflict(left: str, right: str) -> bool:
    if _is_dir(left):
        return right.startswith(left)
    if _is_dir(right):
        return left.startswith(right)
    return False


def explain_conflict(left: Iterable[str], right: Iterable[str]) -> dict[str, Any]:
    left_set = normalize_write_set(left)
    right_set = normalize_write_set(right)

    for a in left_set:
        for b in right_set:
            if a == b:
                return {"conflict": True, "type": "exact", "left": a, "right": b}
            if _is_prefix_conflict(a, b):
                return {"conflict": True, "type": "prefix", "left": a, "right": b}
    return {"conflict": False, "type": None, "left": None, "right": None}


def conflict_between_sets(left: Iterable[str], right: Iterable[str]) -> bool:
    return bool(explain_conflict(left, right)["conflict"])
