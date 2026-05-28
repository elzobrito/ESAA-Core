"""Tests for the `esaa plugin-status` CLI command (FEAT-1900).

Covers the `_plugin_status` helper exported from `esaa.cli`. Uses an
isolated, in-memory fixture under `tmp_path` so no real workspace state is
read or mutated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.cli import _plugin_status
from esaa.errors import ESAAError


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_workspace(root: Path) -> None:
    """Build a workspace where:

      - The projection (roadmap.json) carries 2 tasks: T-001 done, T-002 review.
      - A plugin (roadmap.example.json) declares 4 tasks, all planned `todo`,
        two of which share `task_id` with the projection (T-001, T-002).
    """
    roadmap_dir = root / ".roadmap"
    _write(roadmap_dir / "roadmap.json", {
        "tasks": [
            {"task_id": "T-001", "status": "done", "title": "First", "task_kind": "spec"},
            {"task_id": "T-002", "status": "review", "title": "Second", "task_kind": "impl"},
        ],
    })
    _write(roadmap_dir / "roadmap.example.json", {
        "tasks": [
            {"task_id": "T-001", "status": "todo", "title": "First",  "task_kind": "spec"},
            {"task_id": "T-002", "status": "todo", "title": "Second", "task_kind": "impl"},
            {"task_id": "T-003", "status": "todo", "title": "Third",  "task_kind": "qa"},
            {"task_id": "T-004", "status": "todo", "title": "Fourth", "task_kind": "spec"},
        ],
    })


def test_summary_counts_use_live_status(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    result = _plugin_status(tmp_path)
    assert result["projection_present"] is True
    plugin = next(p for p in result["plugins"] if p["plugin_file"].endswith("roadmap.example.json"))
    assert plugin["tasks_declared"] == 4
    assert plugin["in_projection"] == 2
    assert plugin["by_live_status"] == {"done": 1, "review": 1, "todo": 2}
    assert plugin["by_planned_status"] == {"todo": 4}


def test_filter_by_plugin_name(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    result = _plugin_status(tmp_path, plugin_filter="roadmap.example.json")
    assert len(result["plugins"]) == 1
    assert result["plugins"][0]["plugin_file"].endswith("roadmap.example.json")


def test_detail_mode_emits_per_task_rows(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    result = _plugin_status(tmp_path, detail=True, plugin_filter="roadmap.example.json")
    tasks = result["plugins"][0]["tasks"]
    assert len(tasks) == 4
    by_id = {t["task_id"]: t for t in tasks}
    assert by_id["T-001"]["live_status"] == "done"
    assert by_id["T-002"]["live_status"] == "review"
    assert by_id["T-003"]["live_status"] is None
    assert by_id["T-004"]["live_status"] is None


def test_missing_roadmap_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ESAAError) as exc:
        _plugin_status(tmp_path / "does-not-exist")
    assert exc.value.code == "ROADMAP_DIR_MISSING"


def test_grand_totals_aggregate_all_plugins(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    # Add a second plugin with one task that is also in the projection.
    _write(tmp_path / ".roadmap" / "roadmap.audit.json", {
        "tasks": [
            {"task_id": "T-005", "status": "todo", "title": "Audit", "task_kind": "spec"},
        ],
    })
    result = _plugin_status(tmp_path)
    # roadmap.json contributes its own 2 tasks (done, review).
    # roadmap.example.json contributes 4 (1 done, 1 review, 2 todo).
    # roadmap.audit.json contributes 1 (todo).
    totals = result["grand_totals_by_live_status"]
    assert totals.get("done") == 2
    assert totals.get("review") == 2
    assert totals.get("todo") == 3


def test_schema_file_is_skipped(tmp_path: Path) -> None:
    _make_workspace(tmp_path)
    _write(tmp_path / ".roadmap" / "roadmap.schema.json", {"$schema": "x"})
    result = _plugin_status(tmp_path)
    names = [p["plugin_file"] for p in result["plugins"]]
    assert not any(n.endswith("roadmap.schema.json") for n in names)


def test_unreadable_projection_raises_specific_code(tmp_path: Path) -> None:
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir()
    (roadmap_dir / "roadmap.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(ESAAError) as exc:
        _plugin_status(tmp_path)
    assert exc.value.code == "PROJECTION_UNREADABLE"
