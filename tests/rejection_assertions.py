"""Shared assertions for audited, unapplied agent deliveries (AUD-O1-050)."""
from pathlib import Path

from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store


def assert_only_rejection_events(root: Path, before: int | bytes, code: str, *, repetitions: int = 1) -> None:
    events = parse_event_store(root)
    if isinstance(before, bytes):
        assert (root / ".roadmap/activity.jsonl").read_bytes().startswith(before)
        start = len(before.splitlines())
    else:
        start = before
    added = events[start:]
    assert [event["action"] for event in added] == ["output.rejected", "verify.start", "verify.ok"] * repetitions
    assert all(event["payload"]["error_code"] == code for event in added if event["action"] == "output.rejected")
    # A rejection changes operational metadata only, never task status or content.
    old = materialize(events[:start])[0]
    new = materialize(events)[0]
    assert old["meta"]["run"]["projection_hash_sha256"] == new["meta"]["run"]["projection_hash_sha256"]
    assert ESAAService(root).verify()["verify_status"] == "ok"
