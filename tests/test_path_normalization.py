from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.utils import normalize_rel_path


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".gitignore", ".gitignore"),
        ("../x", "../x"),
        ("./docs/a.md", "docs/a.md"),
        ("./././x", "x"),
        ("a\\b.md", "a/b.md"),
        (".roadmap/lessons.json", ".roadmap/lessons.json"),
        ("docs/.draft.md", "docs/.draft.md"),
        ("/abs/x", "/abs/x"),
    ],
)
def test_normalize_rel_path_strips_only_dot_slash_prefix(raw: str, expected: str) -> None:
    assert normalize_rel_path(raw) == expected


def _claim_spec(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    return svc


def _complete_with(updates: list[dict]) -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": "T-1000",
            "prior_status": "in_progress",
            "verification": {"checks": ["path normalization case"]},
        },
        "file_updates": updates,
    }


@pytest.mark.parametrize(
    ("update", "expected_code"),
    [
        ({"path": "../x", "content": "evil\n"}, "BOUNDARY_VIOLATION"),
        ({"path": ".roadmap/lessons.json", "content": "{}\n"}, "BOUNDARY_VIOLATION"),
        (
            {
                "path": "../x",
                "base_sha256": "0" * 64,
                "edits": [{"old_string": "a", "new_string": "b"}],
            },
            "BOUNDARY_VIOLATION",
        ),
        (
            {
                "path": ".roadmap/lessons.json",
                "base_sha256": "0" * 64,
                "edits": [{"old_string": "a", "new_string": "b"}],
            },
            "BOUNDARY_VIOLATION",
        ),
    ],
)
def test_submit_rejects_traversal_and_governed_state_paths(
    contract_bundle: Path, update: dict, expected_code: str
) -> None:
    svc = _claim_spec(contract_bundle)
    with pytest.raises(ESAAError) as exc:
        svc.submit(_complete_with([update]), actor="agent-spec")
    assert exc.value.code == expected_code


def test_standalone_edits_reject_traversal_with_edit_invalid(tmp_path: Path) -> None:
    from esaa.edits import resolve_edit_updates

    with pytest.raises(ESAAError) as exc:
        resolve_edit_updates(
            tmp_path,
            [
                {
                    "path": "../x",
                    "base_sha256": "0" * 64,
                    "edits": [{"old_string": "a", "new_string": "b"}],
                }
            ],
        )
    assert exc.value.code == "EDIT_INVALID"


def test_dotfile_edit_resolves_against_correct_file(contract_bundle: Path) -> None:
    target = contract_bundle / "docs/.draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    base = "status: draft\n"
    target.write_text(base, encoding="utf-8", newline="")
    svc = _claim_spec(contract_bundle)

    svc.submit(
        _complete_with(
            [
                {
                    "path": "docs/.draft.md",
                    "base_sha256": _sha(base),
                    "edits": [{"old_string": "draft", "new_string": "ready"}],
                }
            ]
        ),
        actor="agent-spec",
    )

    assert target.read_text(encoding="utf-8") == "status: ready\n"


def test_dot_slash_prefix_update_lands_on_normalized_path(contract_bundle: Path) -> None:
    svc = _claim_spec(contract_bundle)

    svc.submit(
        _complete_with([{"path": "./docs/spec/T-1000.md", "content": "ok\n"}]),
        actor="agent-spec",
    )

    assert (contract_bundle / "docs/spec/T-1000.md").read_text(encoding="utf-8") == "ok\n"
