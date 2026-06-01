from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from esaa.cli import main
from esaa.vocabulary import vocabulary_table


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def test_vocabulary_table_marks_historical_and_canonical_terms() -> None:
    table = vocabulary_table()
    by_term = {(row["profile"], row["term"]): row for row in table}

    assert by_term[("paper-v0.3", "promote")]["status"] == "historical"
    assert by_term[("paper-v0.3", "phase.complete")]["maps_to"] == "complete"
    assert by_term[("clinic-asr", "backlog")]["status"] == "profile-specific"
    assert by_term[("core-v0.4.1", "claim")]["status"] == "canonical"
    assert by_term[("core-v0.4.1", "roadmap.activate")]["kind"] == "reserved_orchestrator_action"
    assert by_term[("core-v0.4.1", "done")]["kind"] == "task_status"


def test_vocabulary_cli_is_read_only(contract_bundle: Path) -> None:
    activity_path = contract_bundle / ".roadmap" / "activity.jsonl"
    activity_path.write_text("", encoding="utf-8")
    before = activity_path.read_text(encoding="utf-8")

    result = _run_cli(contract_bundle, "vocabulary")

    assert result["canonical_profile"] == "core-v0.4.1"
    assert "paper-v0.3" in result["profiles"]
    assert activity_path.read_text(encoding="utf-8") == before

