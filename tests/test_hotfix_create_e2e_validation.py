from __future__ import annotations

from pathlib import Path

from test_hotfix_create_validation import (
    test_validate_scope_invalid_empty as _scope_invalid,
)
from test_hotfix_create_validation import (
    test_validate_valid_hotfix_for_done_open_issue as _valid_hotfix,
)
from test_post_survey_fixes import test_create_hotfix_rejects_orphan_request as _orphan


def test_hotfix_create_rejects_orphan(contract_bundle: Path) -> None:
    _orphan(contract_bundle)


def test_hotfix_create_rejects_empty_scope(contract_bundle: Path) -> None:
    _scope_invalid(contract_bundle)


def test_hotfix_create_accepts_done_open_issue(contract_bundle: Path) -> None:
    _valid_hotfix(contract_bundle)
