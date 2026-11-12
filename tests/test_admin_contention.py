"""AUD-O1-050: concurrent administrative writes and audited delivery rejection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from esaa.errors import CorruptedStoreError, ESAAError
from esaa.projector import materialize
from esaa.runtime_policy import count_penalizing_rejections, is_in_cooldown
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "esaa",
            "--root",
            str(root),
            "--runner",
            os.environ.get("ESAA_RUNNER_ID", "unattended"),
            *args,
        ],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
    )


def _complete(task_id: str = "T-A", *, boundary: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "activity_event": {
            "action": "complete",
            "task_id": task_id,
            "prior_status": "in_progress",
            "verification": {"checks": ["unit"]},
        }
    }
    if boundary:
        result["file_updates"] = [{"path": ".roadmap/injected.txt", "content": "forbidden"}]
    return result


def _ready(root: Path, *, cooldown: str = "PT0S") -> ESAAService:
    (root / ".roadmap" / "RUNTIME_POLICY.yaml").write_text(
        f'review_authorization: "qa_role"\nattempt_limits:\n'
        f'  max_attempts_per_task: 3\n  cooldown_between_attempts: "{cooldown}"\n',
        encoding="utf-8",
    )
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "a", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")
    return service


def _only_rejection_added(root: Path, before: list[dict[str, Any]], code: str) -> None:
    events = parse_event_store(root)
    assert events[: len(before)] == before
    added = events[len(before) :]
    assert [e["action"] for e in added] == ["output.rejected", "verify.start", "verify.ok"]
    assert added[0]["payload"]["error_code"] == code
    assert added[0]["payload"]["source_actor"] == "agent-impl"


def test_sixteen_distinct_cli_creates_all_commit(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)
    barrier = Barrier(16)

    def create(index: int) -> subprocess.CompletedProcess[str]:
        barrier.wait(timeout=30)
        return _cli(
            contract_bundle,
            "task",
            "create",
            f"T-{index}",
            "--kind",
            "impl",
            "--title",
            f"task {index}",
            "--output",
            f"src/{index}.txt",
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(create, range(16)))
    failures = [r.stdout + r.stderr for r in results if r.returncode != 0]
    if failures:
        pytest.fail("\n".join(failures), pytrace=False)
    events = parse_event_store(contract_bundle)
    assert [e["event_seq"] for e in events] == list(range(1, len(events) + 1))
    assert len({json.loads(result.stdout)["event_id"] for result in results}) == 16
    for result in results:
        output = json.loads(result.stdout)
        prefix = events[: output["last_event_seq"]]
        assert (
            output["projection_hash_sha256"]
            == materialize(prefix)[0]["meta"]["run"]["projection_hash_sha256"]
        )
        assert prefix[-1]["action"] == "verify.ok"
        assert (
            prefix[-1]["payload"]["projection_hash_sha256"]
            == materialize(prefix[:-1])[0]["meta"]["run"]["projection_hash_sha256"]
        )
    assert len(materialize(events)[0]["tasks"]) == 16
    assert service.verify()["verify_status"] == "ok"


def test_concurrent_same_id_is_rejected_under_lock(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ESAAService(contract_bundle).init(force=True)
    barrier = Barrier(2)
    from esaa.service_core import ESAAServiceCore

    original = ESAAServiceCore._validate_roadmap_projection_schema

    def validate(self: ESAAServiceCore, roadmap: dict[str, Any]) -> None:
        original(self, roadmap)
        barrier.wait(timeout=30)  # both preflight duplicate checks saw the same prefix

    monkeypatch.setattr(ESAAServiceCore, "_validate_roadmap_projection_schema", validate)

    def create(_: int) -> str:
        try:
            ESAAService(contract_bundle).create_task("T-SAME", "impl", "same", outputs=["src/same.txt"])
            return "accepted"
        except ESAAError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == ["DUPLICATE_TASK", "accepted"]
    events = parse_event_store(contract_bundle)
    assert len([e for e in events if e["action"] == "task.create"]) == 1
    assert ESAAService(contract_bundle).verify()["verify_status"] == "ok"


def test_cli_three_boundary_rejections_then_max_attempts(contract_bundle: Path) -> None:
    service = _ready(contract_bundle)
    envelope = contract_bundle / "complete.json"
    envelope.write_text(json.dumps(_complete(boundary=True)), encoding="utf-8")
    for _ in range(3):
        before = parse_event_store(contract_bundle)
        result = _cli(contract_bundle, "submit", "--actor", "agent-impl", str(envelope))
        assert result.returncode == 1
        assert json.loads(result.stderr)["error_code"] == "BOUNDARY_VIOLATION"
        _only_rejection_added(contract_bundle, before, "BOUNDARY_VIOLATION")
    before = (contract_bundle / ".roadmap" / "activity.jsonl").read_bytes()
    result = _cli(contract_bundle, "submit", "--actor", "agent-impl", str(envelope))
    assert result.returncode == 1
    assert json.loads(result.stderr)["error_code"] == "MAX_ATTEMPTS_EXCEEDED"
    assert (contract_bundle / ".roadmap" / "activity.jsonl").read_bytes() == before
    assert not (contract_bundle / ".roadmap" / "injected.txt").exists()
    assert count_penalizing_rejections(parse_event_store(contract_bundle), "T-A") == 3
    assert service.task_state("T-A")["task"]["status"] == "in_progress"
    assert service.verify()["verify_status"] == "ok"


def test_nonpenalizing_workflow_errors_leave_log_unchanged(contract_bundle: Path, repo_root: Path) -> None:
    shutil.copy2(
        repo_root / "src/esaa/templates/roadmap.schema.json", contract_bundle / ".roadmap/roadmap.schema.json"
    )
    service = ESAAService(contract_bundle)
    service.init(force=True)
    service.create_task("T-A", "impl", "a", outputs=["src/a.txt"])
    service.create_task("T-B", "impl", "b", outputs=["src/b.txt"], depends_on=["T-A"])
    service.create_task("T-OLD", "impl", "old", outputs=["src/old.txt"])
    service.create_task("T-NEW", "impl", "new", outputs=["src/new.txt"], supersedes=["T-OLD"])
    cases = [
        (_complete(), "PRIOR_STATUS_MISMATCH"),
        (
            {"activity_event": {"action": "claim", "task_id": "T-B", "prior_status": "todo"}},
            "DEPENDENCY_NOT_DONE",
        ),
        (
            {"activity_event": {"action": "claim", "task_id": "T-OLD", "prior_status": "todo"}},
            "TASK_SUPERSEDED",
        ),
    ]
    for output, code in cases:
        before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
        with pytest.raises(ESAAError) as exc:
            service.submit(output, actor="agent-impl")
        assert exc.value.code == code
        assert code == "PRIOR_STATUS_MISMATCH" or exc.value.penalizes_counter is False
        assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before
        assert (
            count_penalizing_rejections(
                parse_event_store(contract_bundle), output["activity_event"]["task_id"]
            )
            == 0
        )


def test_rejection_enters_scheduler_cooldown(contract_bundle: Path) -> None:
    service = _ready(contract_bundle, cooldown="PT2M")
    service.create_task("T-COOL", "impl", "cool", outputs=["src/cool.txt"])
    assert any(task["task_id"] == "T-COOL" for task in service.eligible()["eligible"])
    invalid_claim = {
        "activity_event": {"action": "claim", "task_id": "T-COOL", "prior_status": "todo"},
        "unknown": True,
    }
    with pytest.raises(ESAAError) as exc:
        service.submit(invalid_claim, actor="agent-impl")
    assert exc.value.code == "SCHEMA_INVALID"
    events = parse_event_store(contract_bundle)
    assert is_in_cooldown(events, "T-COOL", datetime.now(UTC), timedelta(minutes=2))
    assert not any(task["task_id"] == "T-COOL" for task in service.eligible()["eligible"])
    before_run = len(events)
    service.run(steps=1)
    assert not any(
        e["action"] in {"claim", "complete"} and e["payload"].get("task_id") == "T-COOL"
        for e in parse_event_store(contract_bundle)[before_run:]
    )
    assert service.task_state("T-COOL")["task"]["status"] == "todo"


def test_dry_run_error_is_not_recorded(contract_bundle: Path) -> None:
    service = _ready(contract_bundle)
    before = (contract_bundle / ".roadmap/activity.jsonl").read_bytes()
    with pytest.raises(ESAAError) as exc:
        service.submit(_complete(boundary=True), actor="agent-impl", dry_run=True)
    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert (contract_bundle / ".roadmap/activity.jsonl").read_bytes() == before


def test_corrupt_store_is_not_disguised_as_delivery_rejection(contract_bundle: Path) -> None:
    service = _ready(contract_bundle)
    path = contract_bundle / ".roadmap/activity.jsonl"
    with path.open("a") as handle:
        handle.write('{"truncated":')
    before = path.read_bytes()
    with pytest.raises(CorruptedStoreError) as exc:
        service.submit(_complete(boundary=True), actor="agent-impl")
    assert exc.value.code == "JSONL_INVALID"
    assert path.read_bytes() == before


def test_submit_retry_returns_metadata_and_task_from_real_commit(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _ready(contract_bundle)
    original = service._append_events_transactionally
    changed = False

    def concurrent(
        base: list[dict[str, Any]], pending: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal changed
        if not changed:
            changed = True
            ESAAService(contract_bundle).create_task(
                "T-CONCURRENT", "impl", "other", outputs=["src/other.txt"]
            )
        return original(base, pending, **kwargs)

    monkeypatch.setattr(service, "_append_events_transactionally", concurrent)
    result = service.complete_task("T-A", actor="agent-impl", checks=["unit"])
    events = parse_event_store(contract_bundle)
    assert result["last_event_seq"] == events[-1]["event_seq"]
    assert result["projection_hash_sha256"] == materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]
    assert result["task"] == service.task_state("T-A")["task"]
    assert events[-1]["action"] == "verify.ok"
    assert (
        events[-1]["payload"]["projection_hash_sha256"]
        == materialize(events[:-1])[0]["meta"]["run"]["projection_hash_sha256"]
    )
    assert service.verify()["verify_status"] == "ok"


def test_latest_attempt_budget_is_rechecked_under_lock(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _ready(contract_bundle)
    original = service._append_events_transactionally

    def exhaust(base: list[dict[str, Any]], pending: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        for _ in range(3):
            ESAAService(contract_bundle).reject_output(
                "T-A", "BOUNDARY_VIOLATION", "complete", "concurrent failure"
            )
        return original(base, pending, **kwargs)

    monkeypatch.setattr(service, "_append_events_transactionally", exhaust)
    with pytest.raises(ESAAError) as exc:
        service.complete_task("T-A", actor="agent-impl", checks=["unit"])
    assert exc.value.code == "MAX_ATTEMPTS_EXCEEDED"
    assert count_penalizing_rejections(parse_event_store(contract_bundle), "T-A") == 3
    assert service.task_state("T-A")["task"]["status"] == "in_progress"
    assert service.verify()["verify_status"] == "ok"


def test_postcommit_failure_does_not_append_contradictory_rejection(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _ready(contract_bundle)
    import esaa.submission as submission

    def fail_commit(*args: Any) -> None:
        raise ESAAError("BOUNDARY_VIOLATION", "destination changed after append")

    monkeypatch.setattr(submission, "commit_staged", fail_commit)
    output = _complete()
    output["file_updates"] = [{"path": "src/a.txt", "content": "verified bytes"}]
    with pytest.raises(ESAAError, match="destination changed"):
        service.submit(output, actor="agent-impl")
    events = parse_event_store(contract_bundle)
    assert any(e["action"] == "complete" and e["payload"].get("task_id") == "T-A" for e in events)
    assert not any(e["action"] == "output.rejected" for e in events)
    assert service.verify()["verify_status"] == "ok"


@pytest.mark.parametrize("credential", ["missing", "bad-signature", "wrong-principal"])
def test_unauthenticated_boundary_failure_cannot_spend_attempt_budget(
    tmp_path: Path,
    repo_root: Path,
    credential: str,
) -> None:
    from test_actor_registration import _activated, _transition_auth

    service, keys = _activated(tmp_path, repo_root)
    claim_auth = _transition_auth(
        keys["spec"], keys["project_id"], "c1" * 16, "agent-spec", "T-1000", "claim"
    )
    service.claim_task("T-1000", actor="agent-spec", authorization=claim_auth)
    actor = "reviewer-qa" if credential == "wrong-principal" else "agent-spec"
    auth = None
    if credential != "missing":
        key = keys["reviewer"] if credential == "wrong-principal" else keys["spec"]
        auth = _transition_auth(key, keys["project_id"], "c2" * 16, actor, "T-1000", "complete")
        if credential == "bad-signature":
            auth["signature_hex"] = "00" * 64
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    with pytest.raises(ESAAError) as exc:
        service.submit(_complete("T-1000", boundary=True), actor=actor, authorization=auth)
    assert exc.value.code in {
        "ACTOR_AUTH_FAILED",
        "AUTH_SIGNATURE_INVALID",
        "AUTH_SCOPE_MISMATCH",
        "LOCK_VIOLATION",
    }
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    assert count_penalizing_rejections(parse_event_store(tmp_path), "T-1000") == 0
    assert service.verify()["verify_status"] == "ok"


def test_authenticated_boundary_failure_is_audited_with_principal(tmp_path: Path, repo_root: Path) -> None:
    from test_actor_registration import _activated, _transition_auth

    service, keys = _activated(tmp_path, repo_root)
    claim_auth = _transition_auth(
        keys["spec"], keys["project_id"], "c3" * 16, "agent-spec", "T-1000", "claim"
    )
    service.claim_task("T-1000", actor="agent-spec", authorization=claim_auth)
    auth = _transition_auth(keys["spec"], keys["project_id"], "c4" * 16, "agent-spec", "T-1000", "complete")
    with pytest.raises(ESAAError) as exc:
        service.submit(_complete("T-1000", boundary=True), actor="agent-spec", authorization=auth)
    assert exc.value.code == "BOUNDARY_VIOLATION"
    rejected = [e for e in parse_event_store(tmp_path) if e["action"] == "output.rejected"]
    assert len(rejected) == 1
    assert rejected[0]["payload"]["source_actor"] == "agent-spec"
    from esaa.identity import project_registry, resolve_principal

    principal = resolve_principal(project_registry(parse_event_store(tmp_path)), "agent-spec")["principal_id"]
    assert rejected[0]["payload"]["source_principal_id"] == principal
    assert service.verify()["verify_status"] == "ok"


@pytest.mark.parametrize("boundary", [False, True])
def test_unsigned_cli_requests_cannot_block_a_signed_delivery(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: bool,
) -> None:
    from test_actor_registration import _activated, _transition_auth

    from esaa.trust_enrollment import registry_directory

    service, keys = _activated(tmp_path, repo_root)
    # Mirror the fixture's isolated owner enrollment in fresh CLI processes;
    # keep every test binding outside the actual host enrollment registry.
    shim = tmp_path / "cli_site"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(
        "from pathlib import Path\nimport esaa.trust_enrollment as enrollment\n"
        f"enrollment.registry_directory = lambda: Path({str(registry_directory())!r})\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(shim) + os.pathsep + str(repo_root / "src"))
    claim_auth = _transition_auth(
        keys["spec"], keys["project_id"], "d1" * 16, "agent-spec", "T-1000", "claim"
    )
    service.claim_task("T-1000", actor="agent-spec", authorization=claim_auth)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(_complete("T-1000", boundary=boundary)), encoding="utf-8")
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    for _ in range(3):
        result = _cli(tmp_path, "submit", str(request), "--actor", "agent-spec")
        assert result.returncode == 1
        assert json.loads(result.stderr)["error_code"] == "ACTOR_AUTH_FAILED"
        assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    assert count_penalizing_rejections(parse_event_store(tmp_path), "T-1000") == 0
    request.write_text(json.dumps(_complete("T-1000")), encoding="utf-8")
    auth = _transition_auth(keys["spec"], keys["project_id"], "d2" * 16, "agent-spec", "T-1000", "complete")
    auth_path = tmp_path / "authorization.json"
    auth_path.write_text(json.dumps(auth), encoding="utf-8")
    result = _cli(
        tmp_path, "submit", str(request), "--actor", "agent-spec", "--authorization", str(auth_path)
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "accepted"
    assert service.task_state("T-1000")["task"]["status"] == "review"
    assert service.verify()["verify_status"] == "ok"
