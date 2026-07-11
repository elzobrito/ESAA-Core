from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.service import ESAAService
from esaa.snapshot import compact_event_store, create_snapshot, replay_compacted
from esaa.store import parse_event_store


def test_snapshot_dry_run_does_not_write_files(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    result = create_snapshot(contract_bundle, before=3, dry_run=True)

    assert result["status"] == "dry_run"
    assert not (contract_bundle / result["snapshot_path"]).exists()


def test_compaction_writes_snapshot_archive_tail_and_manifest(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)
    service.run(steps=2)
    before_hash = service.verify()["projection_hash_sha256"]

    result = compact_event_store(contract_bundle, before=3, dry_run=False)

    assert result["status"] == "compacted"
    assert (contract_bundle / result["snapshot_path"]).exists()
    assert (contract_bundle / result["archive_path"]).exists()
    assert (contract_bundle / result["tail_path"]).exists()
    manifest = json.loads((contract_bundle / result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["before_event_seq"] == 3
    assert manifest["full_projection_hash_sha256"] == before_hash
    assert replay_compacted(contract_bundle, manifest)["projection_hash_sha256"] == before_hash
    assert parse_event_store(contract_bundle)


def test_compaction_refuses_mismatched_projection(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)
    roadmap_path = contract_bundle / ".roadmap" / "roadmap.json"
    roadmap = json.loads(roadmap_path.read_text(encoding="utf-8"))
    roadmap["meta"]["run"]["verify_status"] = "mismatch"
    roadmap_path.write_text(json.dumps(roadmap), encoding="utf-8")

    with pytest.raises(ESAAError) as excinfo:
        compact_event_store(contract_bundle, before=1)

    assert excinfo.value.code == "VERIFY_NOT_OK"

