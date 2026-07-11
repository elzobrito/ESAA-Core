from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.file_effects import STAGING_DIR, commit_staged, stage_and_compute, verify_artifact
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store
from esaa.validator import validate_file_update_resource_limits


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _claim_spec(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=True)
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
            "verification": {"checks": ["edit update"]},
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


def _edit_update(base: str, old: str, new: str, *, replace_all: bool | None = None) -> dict:
    edit = {"old_string": old, "new_string": new}
    if replace_all is not None:
        edit["replace_all"] = replace_all
    return {
        "path": "docs/spec/T-1000.md",
        "base_sha256": _sha(base),
        "edits": [edit],
    }


def test_submit_resolves_edit_update_and_writes_auditable_artifact(contract_bundle: Path) -> None:
    base = "# Spec\nstatus: draft\n"
    target = _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    result = svc.submit(
        _complete_with([_edit_update(base, "status: draft", "status: ready")]),
        actor="agent-spec",
    )

    assert result["status"] == "accepted"
    assert target.read_text(encoding="utf-8") == "# Spec\nstatus: ready\n"
    write_event = next(
        event for event in parse_event_store(contract_bundle) if event["action"] == "orchestrator.file.write"
    )
    effect = write_event["payload"]["effects"][0]
    assert effect["before_sha256"] == _sha(base)
    assert effect["after_sha256"] == _sha("# Spec\nstatus: ready\n")
    ok, error = verify_artifact(contract_bundle, effect["artifact_path"])
    assert ok is True
    assert error is None


def test_apply_edits_are_sequential_and_support_replace_all(contract_bundle: Path) -> None:
    base = "one = old\nalias = one\none = old\n"
    target = _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    svc.submit(
        _complete_with(
            [
                {
                    "path": "docs/spec/T-1000.md",
                    "base_sha256": _sha(base),
                    "edits": [
                        {"old_string": "alias = one", "new_string": "alias = new"},
                        {"old_string": "one = old", "new_string": "one = new", "replace_all": True},
                    ],
                }
            ]
        ),
        actor="agent-spec",
    )

    assert target.read_text(encoding="utf-8") == "one = new\nalias = new\none = new\n"


@pytest.mark.parametrize(
    ("base", "update", "expected_code"),
    [
        (
            "alpha\n",
            {
                "path": "docs/spec/T-1000.md",
                "base_sha256": _sha("other\n"),
                "edits": [{"old_string": "alpha", "new_string": "beta"}],
            },
            "EDIT_BASE_MISMATCH",
        ),
        (
            "alpha\n",
            {
                "path": "docs/spec/missing.md",
                "base_sha256": _sha("alpha\n"),
                "edits": [{"old_string": "alpha", "new_string": "beta"}],
            },
            "EDIT_BASE_MISMATCH",
        ),
        (
            "alpha\n",
            {
                "path": "docs/spec/T-1000.md",
                "base_sha256": _sha("alpha\n"),
                "edits": [{"old_string": "gamma", "new_string": "beta"}],
            },
            "EDIT_TARGET_NOT_FOUND",
        ),
        (
            "alpha alpha\n",
            {
                "path": "docs/spec/T-1000.md",
                "base_sha256": _sha("alpha alpha\n"),
                "edits": [{"old_string": "alpha", "new_string": "beta"}],
            },
            "EDIT_AMBIGUOUS",
        ),
    ],
)
def test_submit_rejects_invalid_edit_runtime_cases_without_store_or_staging_change(
    contract_bundle: Path,
    base: str,
    update: dict,
    expected_code: str,
) -> None:
    _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(_complete_with([update]), actor="agent-spec")

    assert exc.value.code == expected_code
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


@pytest.mark.parametrize(
    "update",
    [
        {
            "path": "docs/spec/T-1000.md",
            "base_sha256": _sha("alpha\n"),
            "content": "beta\n",
            "edits": [{"old_string": "alpha", "new_string": "beta"}],
        },
        {"path": "docs/spec/T-1000.md", "base_sha256": _sha("alpha\n"), "edits": []},
    ],
)
def test_submit_rejects_schema_invalid_edit_shapes(contract_bundle: Path, update: dict) -> None:
    _seed_target(contract_bundle, "alpha\n")
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(_complete_with([update]), actor="agent-spec")

    assert exc.value.code == "SCHEMA_INVALID"
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_edit_invalid_is_available_for_standalone_runtime_validation(contract_bundle: Path) -> None:
    from esaa.edits import resolve_edit_updates

    _seed_target(contract_bundle, "alpha\n")
    with pytest.raises(ESAAError) as exc:
        resolve_edit_updates(
            contract_bundle,
            [
                {
                    "path": "docs/spec/T-1000.md",
                    "base_sha256": _sha("alpha\n"),
                    "edits": [{"old_string": "alpha", "new_string": "alpha"}],
                }
            ],
        )
    assert exc.value.code == "EDIT_INVALID"


def test_boundary_violation_precedes_edit_resolution(contract_bundle: Path) -> None:
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {
                        "path": "src/not-allowed.py",
                        "base_sha256": _sha("missing"),
                        "edits": [{"old_string": "missing", "new_string": "x"}],
                    }
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_dry_run_resolves_edits_without_writing_files(contract_bundle: Path) -> None:
    base = "# Spec\nstatus: draft\n"
    target = _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    result = svc.submit(
        _complete_with([_edit_update(base, "status: draft", "status: ready")]),
        actor="agent-spec",
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["would_append_events"] >= 1
    assert target.read_text(encoding="utf-8") == base
    assert _staging_files(contract_bundle) == []


def test_resource_limits_run_after_edit_expansion_and_support_standalone_edit_items(
    contract_bundle: Path,
) -> None:
    base = "short\n"
    _seed_target(contract_bundle, base)
    policy = {"resource_limits": {"max_file_updates": 1, "max_bytes_per_update": 8, "max_bytes_total": 8}}
    policy_path = contract_bundle / ".roadmap/RUNTIME_POLICY.yaml"
    policy_path.write_text(
        "resource_limits:\n  max_file_updates: 1\n  max_bytes_per_update: 8\n  max_bytes_total: 8\n",
        encoding="utf-8",
    )
    svc = _claim_spec(contract_bundle)

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with([_edit_update(base, "short", "this is much longer")]),
            actor="agent-spec",
        )

    assert exc.value.code == "RESOURCE_LIMIT_EXCEEDED"
    with pytest.raises(ESAAError) as standalone:
        validate_file_update_resource_limits(
            [{"path": "docs/spec/T-1000.md", "edits": [{"old_string": "1234", "new_string": "56789"}]}],
            policy,
        )
    assert standalone.value.code == "RESOURCE_LIMIT_EXCEEDED"


def test_staging_preserves_utf8_bytes_used_for_after_hash_on_windows(contract_bundle: Path) -> None:
    content = "line 1\nline 2\n"
    staged, effects = stage_and_compute(
        contract_bundle, [{"path": "docs/spec/T-1000.md", "content": content}]
    )

    commit_staged(contract_bundle, staged)

    final_bytes = (contract_bundle / "docs/spec/T-1000.md").read_bytes()
    assert hashlib.sha256(final_bytes).hexdigest() == effects[0]["after_sha256"]


def test_edit_updates_preserve_replay_determinism(contract_bundle: Path) -> None:
    base = "# Spec\nstatus: draft\n"
    _seed_target(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    svc.submit(
        _complete_with([_edit_update(base, "status: draft", "status: ready")]),
        actor="agent-spec",
    )

    events = parse_event_store(contract_bundle)
    first = materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]
    second = materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]

    assert first == second


def test_single_run_edit_with_stale_disk_base_is_write_conflict(contract_bundle: Path) -> None:
    import json as _json

    from esaa.adapters.base import AgentAdapter

    base = "status: base\n"
    target = contract_bundle / "docs/spec/shared-edit.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(base, encoding="utf-8", newline="")

    class EditClobberAdapter(AgentAdapter):
        agent_id = "agent-spec"

        def health(self) -> dict[str, str]:
            return {"status": "ok"}

        def execute(self, dispatch_context: dict) -> dict:
            task = dispatch_context["task"]
            if task["status"] == "todo":
                return {
                    "activity_event": {
                        "action": "claim",
                        "task_id": task["task_id"],
                        "prior_status": "todo",
                    }
                }
            if task["status"] == "in_progress":
                if task["task_id"] == "P-1":
                    update = {"path": "docs/spec/shared-edit.md", "content": "status: P-1\n"}
                else:
                    # base_sha256 casa com o DISCO (P-1 ainda staged) â€” antes do M1
                    # isto passava e clobberava P-1 no commit.
                    update = {
                        "path": "docs/spec/shared-edit.md",
                        "base_sha256": _sha(base),
                        "edits": [{"old_string": "base", "new_string": "P-2"}],
                    }
                return {
                    "activity_event": {
                        "action": "complete",
                        "task_id": task["task_id"],
                        "prior_status": "in_progress",
                        "verification": {"checks": ["shared edit write"]},
                    },
                    "file_updates": [update],
                }
            return {
                "activity_event": {
                    "action": "review",
                    "task_id": task["task_id"],
                    "prior_status": "review",
                    "decision": "approve",
                    "tasks": [task["task_id"]],
                }
            }

    (contract_bundle / ".roadmap" / "roadmap.editclobber.json").write_text(
        _json.dumps(
            {
                "project": {"name": "edit-clobber"},
                "tasks": [
                    {
                        "task_id": "P-1",
                        "task_kind": "spec",
                        "title": "P1",
                        "depends_on": [],
                        "outputs": {"files": ["docs/spec/p1.md"]},
                    },
                    {
                        "task_id": "P-2",
                        "task_kind": "spec",
                        "title": "P2",
                        "depends_on": ["P-1"],
                        "outputs": {"files": ["docs/spec/p2.md"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    svc = ESAAService(contract_bundle, adapter=EditClobberAdapter())
    svc.init(force=True, with_demo_tasks=True)
    result = svc.run(steps=None, parallel=1)

    assert (contract_bundle / "docs/spec/shared-edit.md").read_text(encoding="utf-8") == "status: P-1\n"
    rejected = [event for event in parse_event_store(contract_bundle) if event["action"] == "output.rejected"]
    assert any(event["payload"]["error_code"] == "WRITE_CONFLICT" for event in rejected)
    assert result["rejected"] >= 1
    assert svc.verify()["verify_status"] == "ok"
