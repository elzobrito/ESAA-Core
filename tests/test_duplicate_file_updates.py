"""Regressao ISS-T2042-DUP-FILE-UPDATES (HF-ISS-T2042-DUP-FILE-UPDATES).

Um unico complete com dois file_updates para o mesmo path normalizado era
aceito: o staging aplicava ambos os efeitos e o ultimo write vencia
silenciosamente. Agora o Orchestrator rejeita com FILE_UPDATE_DUPLICATE_PATH
apos a resolucao de edits e antes de resource limits / staging.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.file_effects import STAGING_DIR
from esaa.service import ESAAService
from esaa.store import parse_event_store
from esaa.validator import validate_unique_file_update_paths


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
            "verification": {"checks": ["duplicate path rejection"]},
        },
        "file_updates": updates,
    }


def _staging_files(root: Path) -> list[Path]:
    staging = root / STAGING_DIR
    if not staging.exists():
        return []
    return [path for path in staging.rglob("*") if path.is_file()]


def _seed_target(root: Path, content: str) -> Path:
    target = root / "docs/spec/T-1000.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    return target


def test_validate_unique_file_update_paths_accepts_unique_paths() -> None:
    validate_unique_file_update_paths(
        [
            {"path": "docs/spec/a.md", "content": "a"},
            {"path": "docs/spec/b.md", "content": "b"},
        ]
    )


def test_validate_unique_file_update_paths_rejects_duplicate() -> None:
    with pytest.raises(ESAAError) as exc:
        validate_unique_file_update_paths(
            [
                {"path": "docs/spec/T-1000.md", "content": "first"},
                {"path": "docs/spec/T-1000.md", "content": "second"},
            ]
        )
    assert exc.value.code == "FILE_UPDATE_DUPLICATE_PATH"


def test_submit_rejects_duplicate_content_paths_without_store_or_staging_change(
    contract_bundle: Path,
) -> None:
    base = "# Spec\nstatus: draft\n"
    target = _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {"path": "docs/spec/T-1000.md", "content": "first write\n"},
                    {"path": "docs/spec/T-1000.md", "content": "second write\n"},
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "FILE_UPDATE_DUPLICATE_PATH"
    assert target.read_text(encoding="utf-8") == base
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_submit_rejects_duplicate_edit_updates_with_same_base_sha(contract_bundle: Path) -> None:
    # Repro da issue: dois edit updates para o mesmo path, ambos com o mesmo
    # base_sha256 do arquivo em disco; cada um resolve individualmente, mas o
    # par e rejeitado antes de staging.
    base = "status: draft\n"
    target = _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {
                        "path": "docs/spec/T-1000.md",
                        "base_sha256": _sha(base),
                        "edits": [{"old_string": "draft", "new_string": "ready"}],
                    },
                    {
                        "path": "docs/spec/T-1000.md",
                        "base_sha256": _sha(base),
                        "edits": [{"old_string": "draft", "new_string": "final"}],
                    },
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "FILE_UPDATE_DUPLICATE_PATH"
    assert target.read_text(encoding="utf-8") == base
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_submit_rejects_duplicate_after_separator_normalization(contract_bundle: Path) -> None:
    base = "# Spec\n"
    _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {"path": "docs/spec/T-1000.md", "content": "forward\n"},
                    {"path": "docs\\spec\\T-1000.md", "content": "backslash\n"},
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "FILE_UPDATE_DUPLICATE_PATH"


def test_dry_run_also_rejects_duplicate_paths(contract_bundle: Path) -> None:
    base = "# Spec\n"
    _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {"path": "docs/spec/T-1000.md", "content": "first\n"},
                    {"path": "docs/spec/T-1000.md", "content": "second\n"},
                ]
            ),
            actor="agent-spec",
            dry_run=True,
        )

    assert exc.value.code == "FILE_UPDATE_DUPLICATE_PATH"


def test_distinct_paths_still_accepted_in_single_complete(contract_bundle: Path) -> None:
    svc = _claim_spec(contract_bundle)

    result = svc.submit(
        _complete_with(
            [
                {"path": "docs/spec/T-1000.md", "content": "spec\n"},
                {"path": "docs/spec/T-1000-notes.md", "content": "notes\n"},
            ]
        ),
        actor="agent-spec",
    )

    assert result["status"] == "accepted"
    assert result["files_written"] == 2
    assert (contract_bundle / "docs/spec/T-1000.md").read_text(encoding="utf-8") == "spec\n"
    assert (contract_bundle / "docs/spec/T-1000-notes.md").read_text(encoding="utf-8") == "notes\n"
