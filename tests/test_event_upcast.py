from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from esaa.compat import normalize_legacy_verify_status, upcast_event
from esaa.constants import CANONICAL_ACTIONS, SCHEMA_VERSION
from esaa.errors import CorruptedStoreError, ESAAError
from esaa.event_schema import list_covered_actions, load_event_schema, validate_event_for_append
from esaa.events import make_event
from esaa.projector import materialize
from esaa.reject_codes import EVENT_SCHEMA_INVALID, UNSUPPORTED_EVENT_SCHEMA_VERSION
from esaa.store_runtime import append_events, append_transactional, parse_event_store

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "logs"
REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSIONS = [
    "v0.5.0b19",
    "v0.5.0b20",
    "v0.5.0b21",
    "v0.5.0b22",
    "v0.5.0b23",
    "v0.5.0b24",
    "v0.5.0b25",
]


def test_event_schema_covers_all_canonical_actions_1_to_1() -> None:
    schema = load_event_schema()
    enum_actions = set(schema["properties"]["action"]["enum"])
    covered_actions = set(list_covered_actions())
    canonical = set(CANONICAL_ACTIONS)

    assert enum_actions == canonical
    assert covered_actions == canonical
    assert len(list_covered_actions()) == len(CANONICAL_ACTIONS)


def test_repo_activity_jsonl_validates_after_upcast(live_identity_pin: Path) -> None:
    activity_path = live_identity_pin / ".roadmap" / "activity.jsonl"
    if not activity_path.exists():
        pytest.skip("repository .roadmap/activity.jsonl not present")

    events = parse_event_store(live_identity_pin)
    assert events
    for event in events:
        upcasted = upcast_event(event)
        validate_event_for_append(upcasted)


@pytest.mark.parametrize("version_tag", EXPECTED_VERSIONS)
def test_historical_fixture_replay_and_upcast(tmp_path: Path, version_tag: str) -> None:
    fixture_dir = FIXTURES_ROOT / version_tag
    assert fixture_dir.is_dir(), f"missing fixture directory: {fixture_dir}"

    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_dir / "activity.jsonl", roadmap_dir / "activity.jsonl")
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))

    events = parse_event_store(tmp_path)
    assert len(events) == expected["last_event_seq"]
    for event in events:
        validate_event_for_append(upcast_event(event))

    roadmap, issues, lessons = materialize(events)
    assert roadmap["meta"]["run"]["last_event_seq"] == expected["last_event_seq"]
    assert roadmap["meta"]["run"]["verify_status"] == expected["verify_status"]
    assert len(roadmap["tasks"]) == expected["task_count"]
    assert len(issues["issues"]) == expected["issue_count"]
    assert len(lessons["lessons"]) == expected["lesson_count"]
    assert (
        roadmap["meta"]["run"]["projection_hash_sha256"]
        == materialize(events)[0]["meta"]["run"]["projection_hash_sha256"]
    )


def test_append_events_rejects_invalid_event_with_zero_side_effects(tmp_path: Path) -> None:
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    seed = make_event(1, "orchestrator", "run.start", {"project": "test"})
    append_events(tmp_path, [seed])
    before_bytes = (roadmap_dir / "activity.jsonl").read_bytes()

    invalid = make_event(2, "agent-impl", "complete", {})  # missing required payload.task_id
    with pytest.raises(ESAAError) as exc_info:
        append_events(tmp_path, [invalid])

    assert exc_info.value.code == EVENT_SCHEMA_INVALID
    assert "complete" in exc_info.value.message
    assert "task_id" in exc_info.value.message
    assert (roadmap_dir / "activity.jsonl").read_bytes() == before_bytes


def test_append_transactional_rejects_invalid_event_without_running_after_append(tmp_path: Path) -> None:
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    seed = make_event(1, "orchestrator", "run.start", {"project": "test"})
    append_events(tmp_path, [seed])
    before_bytes = (roadmap_dir / "activity.jsonl").read_bytes()
    side_effect_file = tmp_path / "should_not_exist.txt"

    def build(_current: list[dict]) -> list[dict]:
        return [make_event(2, "agent-qa", "review", {"task_id": "T-1"})]  # missing decision

    with pytest.raises(ESAAError) as exc_info:
        append_transactional(
            tmp_path,
            build,
            after_append=lambda: side_effect_file.write_text("mutated", encoding="utf-8"),
        )

    assert exc_info.value.code == EVENT_SCHEMA_INVALID
    assert "review" in exc_info.value.message
    assert "decision" in exc_info.value.message
    assert not side_effect_file.exists()
    assert (roadmap_dir / "activity.jsonl").read_bytes() == before_bytes


def test_replay_does_not_call_append_schema_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    legacy_line = json.dumps(
        {
            "event_seq": 1,
            "ts": "2026-01-01T00:00:00Z",
            "actor": "orchestrator",
            "action": "run.start",
            "payload": {},
        }
    )
    (roadmap_dir / "activity.jsonl").write_text(legacy_line + "\n", encoding="utf-8")

    def boom(_event: dict) -> None:
        raise AssertionError("validate_event_for_append must not be called during replay")

    monkeypatch.setattr("esaa.event_schema.validate_event_for_append", boom)
    events = parse_event_store(tmp_path)
    assert len(events) == 1
    assert events[0]["schema_version"] == SCHEMA_VERSION
    assert events[0]["event_id"] == "LEGACY-EV-00000001"


def test_upcaster_chain_idempotence_cycle_and_unknown_version() -> None:
    raw_030 = {
        "event_seq": 7,
        "ts": "2026-01-01T00:00:00Z",
        "actor": "orchestrator",
        "action": "verify.fail",
        "payload": {"verify_status": "fail"},
    }
    raw_snapshot = json.dumps(raw_030, sort_keys=True)

    up1 = upcast_event(raw_030)
    up2 = upcast_event(up1)

    assert json.dumps(raw_030, sort_keys=True) == raw_snapshot
    assert up1 == up2
    assert up1["schema_version"] == SCHEMA_VERSION
    assert normalize_legacy_verify_status(up1["payload"]["verify_status"]) == "mismatch"

    cyclic_registry = {
        "0.3.0": ("0.4.0", lambda ev: ev),
        "0.4.0": ("0.3.0", lambda ev: ev),
    }
    with pytest.raises(CorruptedStoreError) as cycle_exc:
        upcast_event(raw_030, registry=cyclic_registry)
    assert cycle_exc.value.code == UNSUPPORTED_EVENT_SCHEMA_VERSION

    with pytest.raises(CorruptedStoreError) as unknown_exc:
        upcast_event({**raw_030, "schema_version": "0.1.0"})
    assert unknown_exc.value.code == UNSUPPORTED_EVENT_SCHEMA_VERSION


PUBLISHED_HISTORICAL_RELEASES = [
    "0.5.0b1",
    "0.5.0b2",
    "0.5.0b3",
    "0.5.0b4",
    "0.5.0b5",
    "0.5.0b6",
    "0.5.0b7",
    "0.5.0b8",
    "0.5.0b9",
    "0.5.0b10",
    "0.5.0b11",
    "0.5.0b13",
    "0.5.0b14",
    "0.5.0b17",
    "0.5.0b18",
    "0.5.0b19",
    "0.5.0b20",
    "0.5.0b21",
    "0.5.0b22",
    "0.5.0b23",
    "0.5.0b24",
    "0.5.0b25",
    "0.5.0b26",
    "0.5.0b27",
    "0.5.0b29",
]
RELEASES_WITHOUT_RUNNER = {"0.5.0b1", "0.5.0b2", "0.5.0b3", "0.5.0b4", "0.5.0b5"}


def test_all_25_published_releases_event_count_and_sha256() -> None:
    import hashlib

    total_events = 0
    b1_b5_events = 0
    b6_b29_events = 0
    for tag in PUBLISHED_HISTORICAL_RELEASES:
        fixture_dir = FIXTURES_ROOT / tag
        expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))
        raw_bytes = (fixture_dir / "activity.jsonl").read_bytes()
        assert hashlib.sha256(raw_bytes).hexdigest() == expected["log_sha256"]
        count = len([ln for ln in raw_bytes.decode("utf-8").splitlines() if ln.strip()])
        assert count == expected["last_event_seq"]
        total_events += count
        if tag in RELEASES_WITHOUT_RUNNER:
            b1_b5_events += count
        else:
            b6_b29_events += count
    assert len(PUBLISHED_HISTORICAL_RELEASES) == 25
    assert total_events == 601
    assert b1_b5_events == 125
    assert b6_b29_events == 476


@pytest.mark.parametrize("release_tag", PUBLISHED_HISTORICAL_RELEASES)
def test_published_historical_release_replay_upcast_and_legacy_hash(tmp_path: Path, release_tag: str) -> None:
    from esaa.projector import compute_projection_hash

    fixture_dir = FIXTURES_ROOT / release_tag
    assert fixture_dir.is_dir(), f"missing published fixture directory: {fixture_dir}"

    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_dir / "activity.jsonl", roadmap_dir / "activity.jsonl")
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))

    events = parse_event_store(tmp_path)
    assert len(events) == expected["last_event_seq"]

    for ev in events:
        up = upcast_event(ev)
        if release_tag in RELEASES_WITHOUT_RUNNER:
            # Authorized owner exception: 125 events in b1-b5 preserve absence of runner.
            assert "runner" not in ev
            assert "runner" not in up
        else:
            validate_event_for_append(up)

    roadmap, _issues, _lessons = materialize(events)
    assert roadmap["meta"]["run"]["last_event_seq"] == expected["last_event_seq"]
    from esaa.constants import VIEW_SCHEMA_VERSION

    assert roadmap["meta"]["schema_version"] == VIEW_SCHEMA_VERSION
    assert compute_projection_hash(roadmap) == expected["projection_hash_sha256"]


def test_new_append_on_b1_store_requires_current_runner_provenance(tmp_path: Path) -> None:
    fixture_dir = FIXTURES_ROOT / "0.5.0b1"
    roadmap_dir = tmp_path / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_dir / "activity.jsonl", roadmap_dir / "activity.jsonl")

    events = parse_event_store(tmp_path)
    new_ev = make_event(len(events) + 1, "orchestrator", "runner.metrics", {"task_id": "HISTORY-001"})
    append_events(tmp_path, [new_ev])

    updated_events = parse_event_store(tmp_path)
    assert len(updated_events) == len(events) + 1
    assert all("runner" not in ev for ev in updated_events[:-1])
    assert isinstance(updated_events[-1].get("runner"), dict)
    assert updated_events[-1]["runner"].get("runner_id")
    validate_event_for_append(updated_events[-1])

    from esaa.provenance import validate_runner_block

    with pytest.raises(ESAAError):
        validate_runner_block({"invalid": 1})
