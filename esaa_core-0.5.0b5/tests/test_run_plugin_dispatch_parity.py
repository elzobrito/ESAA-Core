from __future__ import annotations

from pathlib import Path

from test_post_survey_fixes import test_run_consumes_late_plugin_task as _scenario


def test_run_consumes_plugin_task_from_same_view(tmp_path: Path, repo_root: Path) -> None:
    _scenario(tmp_path, repo_root)
