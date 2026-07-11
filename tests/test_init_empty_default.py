from __future__ import annotations

import json
from pathlib import Path

from esaa.bootstrap import bootstrap_workspace
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _boot(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    bootstrap_workspace(root, profile="public")
    return root


def test_init_default_has_no_demo_tasks(tmp_path: Path) -> None:
    root = _boot(tmp_path)
    result = ESAAService(root).init()
    assert result["task_source"] == "empty"
    assert result["tasks_seeded"] == []
    assert result["with_demo_tasks"] is False
    roadmap = json.loads((root / ".roadmap" / "roadmap.json").read_text(encoding="utf-8"))
    ids = {t["task_id"] for t in roadmap["tasks"]}
    assert "T-1000" not in ids
    assert "T-1010" not in ids
    assert "T-1020" not in ids
    assert roadmap["tasks"] == []


def test_init_with_demo_tasks_seeds_baseline_track(tmp_path: Path) -> None:
    root = _boot(tmp_path)
    result = ESAAService(root).init(with_demo_tasks=True)
    assert result["task_source"] == "demo"
    assert result["tasks_seeded"] == ["T-1000", "T-1010", "T-1020"]
    roadmap = json.loads((root / ".roadmap" / "roadmap.json").read_text(encoding="utf-8"))
    ids = {t["task_id"] for t in roadmap["tasks"]}
    assert ids == {"T-1000", "T-1010", "T-1020"}
    eligible = ESAAService(root).eligible()
    assert eligible["eligible_count"] >= 1
    assert any(t["task_id"] == "T-1000" for t in eligible["eligible"])


def test_init_cli_with_demo_tasks_flag(tmp_path: Path) -> None:
    import contextlib
    import io
    from esaa.cli import main

    root = _boot(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["--root", str(root), "init", "--with-demo-tasks"])
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["task_source"] == "demo"
    assert "T-1000" in payload["tasks_seeded"]


def test_init_cli_default_empty(tmp_path: Path) -> None:
    import contextlib
    import io
    from esaa.cli import main

    root = _boot(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["--root", str(root), "init"])
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["task_source"] == "empty"
    assert payload["tasks_seeded"] == []
