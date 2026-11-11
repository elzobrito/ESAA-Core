from __future__ import annotations

from pathlib import Path

import pytest
from test_post_survey_fixes import test_file_effect_can_recover_after_final_commit_failure as _scenario


def test_file_effect_recovery_flow(contract_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _scenario(contract_bundle, monkeypatch)
