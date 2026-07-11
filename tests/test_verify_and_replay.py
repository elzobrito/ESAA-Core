from __future__ import annotations

import json
from pathlib import Path

from esaa.service import ESAAService


def test_verify_ok_then_mismatch_and_corrupted(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)
    service.run(steps=9)

    ok = service.verify()
    assert ok["verify_status"] == "ok"

    roadmap_path = contract_bundle / ".roadmap/roadmap.json"
    roadmap = json.loads(roadmap_path.read_text(encoding="utf-8"))
    roadmap["meta"]["run"]["projection_hash_sha256"] = "0" * 64
    roadmap_path.write_text(json.dumps(roadmap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mismatch = service.verify()
    assert mismatch["verify_status"] == "mismatch"

    activity_path = contract_bundle / ".roadmap/activity.jsonl"
    activity_path.write_text("{not-json}\n", encoding="utf-8")
    corrupted = service.verify()
    assert corrupted["verify_status"] == "corrupted"


def test_replay_until_seq(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)
    service.run(steps=2)
    out = service.replay(until="2", write_views=False)
    assert out["events_replayed"] == 2
    assert out["last_event_seq"] == 2

