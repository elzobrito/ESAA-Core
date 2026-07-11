from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest
import yaml

from esaa.cli import main
from esaa.errors import CorruptedStoreError
from esaa.service import ESAAService, make_event
from esaa.store import append_events, init_hash_chain, next_event_seq, parse_event_store, verify_hash_chain


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _activity_lines(root: Path) -> list[str]:
    return (root / ".roadmap" / "activity.jsonl").read_text(encoding="utf-8").splitlines()


def _write_activity_lines(root: Path, lines: list[str]) -> None:
    (root / ".roadmap" / "activity.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _enable_qa_role_policy(root: Path) -> None:
    policy_path = root / ".roadmap" / "RUNTIME_POLICY.yaml"
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    data["review_authorization"] = "qa_role"
    policy_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _append_orchestrator_event(root: Path, action: str = "runner.metrics") -> dict:
    events = parse_event_store(root)
    event = make_event(
        next_event_seq(events),
        "orchestrator",
        action,
        {"runner_id": "qa-chain", "metrics": {"duration_ms": 1}},
    )
    append_events(root, [event])
    return parse_event_store(root)[-1]


def test_chain_init_and_verify_cover_events_after_anchor(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True, with_demo_tasks=True)

    assert _run_cli(contract_bundle, "verify", "--chain")["chain_status"] == "unanchored"
    anchor = _run_cli(contract_bundle, "chain", "init")
    assert anchor["status"] == "anchored"

    appended = _append_orchestrator_event(contract_bundle)
    verified = _run_cli(contract_bundle, "verify", "--chain")

    assert verified["chain_status"] == "ok"
    assert verified["anchored_through_seq"] == anchor["anchored_through_seq"]
    assert appended["prev_event_hash"] == anchor["anchor_sha256"]
    assert appended["event_hash"]


def test_post_anchor_payload_tamper_breaks_parse_and_verify(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True, with_demo_tasks=True)
    init_hash_chain(contract_bundle)
    _append_orchestrator_event(contract_bundle)

    lines = _activity_lines(contract_bundle)
    last = json.loads(lines[-1])
    last["payload"]["metrics"]["duration_ms"] = 999
    lines[-1] = json.dumps(last, ensure_ascii=False, separators=(",", ":"))
    _write_activity_lines(contract_bundle, lines)

    with pytest.raises(CorruptedStoreError) as excinfo:
        parse_event_store(contract_bundle)
    assert excinfo.value.code == "CHAIN_BROKEN"
    assert verify_hash_chain(contract_bundle)["chain_status"] == "broken"


def test_pre_anchor_tamper_breaks_anchor_hash(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True, with_demo_tasks=True)
    init_hash_chain(contract_bundle)

    lines = _activity_lines(contract_bundle)
    first = json.loads(lines[0])
    first["payload"]["status"] = "tampered"
    lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
    _write_activity_lines(contract_bundle, lines)

    with pytest.raises(CorruptedStoreError) as excinfo:
        parse_event_store(contract_bundle)
    assert excinfo.value.code == "CHAIN_BROKEN"
    assert verify_hash_chain(contract_bundle)["error_code"] == "CHAIN_BROKEN"


def test_review_role_is_top_level_and_hash_protected(contract_bundle: Path) -> None:
    ESAAService(contract_bundle).init(force=True, with_demo_tasks=True)
    _enable_qa_role_policy(contract_bundle)
    init_hash_chain(contract_bundle)
    _run_cli(contract_bundle, "claim", "T-1000", "--actor", "agent-spec")

    updates = contract_bundle / "updates.json"
    updates.write_text(
        json.dumps([{"path": "docs/spec/T-1000.md", "content": "# Chain QA\n"}]),
        encoding="utf-8",
    )
    _run_cli(
        contract_bundle,
        "complete",
        "T-1000",
        "--actor",
        "agent-spec",
        "--check",
        "chain qa complete",
        "--file-updates",
        str(updates),
    )
    _run_cli(contract_bundle, "review", "T-1000", "--actor", "agent-qa", "--decision", "approve")

    events = parse_event_store(contract_bundle)
    review = next(event for event in events if event["action"] == "review")
    assert review["reviewer_role"] == "qa"
    assert "_reviewer_role" not in review["payload"]
    assert review["event_hash"]

    lines = _activity_lines(contract_bundle)
    review_index = next(i for i, line in enumerate(lines) if json.loads(line)["action"] == "review")
    forged = json.loads(lines[review_index])
    forged["reviewer_role"] = "owner"
    lines[review_index] = json.dumps(forged, ensure_ascii=False, separators=(",", ":"))
    _write_activity_lines(contract_bundle, lines)

    with pytest.raises(CorruptedStoreError) as excinfo:
        parse_event_store(contract_bundle)
    assert excinfo.value.code == "CHAIN_BROKEN"
