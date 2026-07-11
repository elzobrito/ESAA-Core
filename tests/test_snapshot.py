from __future__ import annotations

import json
from pathlib import Path

from esaa.service import ESAAService
from esaa.snapshot import create_snapshot


def test_create_snapshot_writes_projection_checkpoint(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)
    service.run(steps=1)

    result = create_snapshot(contract_bundle, before=3)

    snapshot_path = contract_bundle / result["snapshot_path"]
    assert snapshot_path.exists()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["snapshot"]["before_event_seq"] == 3
    assert payload["snapshot"]["events_included"] == 3
    assert payload["roadmap"]["meta"]["run"]["last_event_seq"] == 3
    assert payload["roadmap"]["meta"]["run"]["projection_hash_sha256"]

