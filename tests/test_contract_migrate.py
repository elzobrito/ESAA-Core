import json
import shutil
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from esaa.bootstrap import bootstrap_workspace
from esaa.contract_migrate import migrate_active_contracts, revert_active_contracts
from esaa.errors import ESAAError
from esaa.service import ESAAService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy_contracts"


def _workspace(tmp_path):
    bootstrap_workspace(tmp_path)
    svc = ESAAService(tmp_path)
    svc.init()
    return svc


def _install_legacy(root: Path) -> None:
    for name in ("agent_result.schema.json", "roadmap.schema.json"):
        shutil.copy(FIXTURES / name, root / ".roadmap" / name)


def test_legacy_schema_rejects_binary_until_migrate(tmp_path):
    svc = _workspace(tmp_path)
    _install_legacy(tmp_path)
    activity = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    roadmap = (tmp_path / ".roadmap/roadmap.json").read_bytes()
    dry = migrate_active_contracts(tmp_path, dry_run=True)
    assert dry["status"] == "migrated"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == activity
    result = migrate_active_contracts(tmp_path)
    assert result["status"] == "migrated"
    assert ".roadmap/agent_result.schema.json" in result["files_changed"]
    assert ".roadmap/roadmap.schema.json" in result["files_changed"]
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == activity
    assert (tmp_path / ".roadmap/roadmap.json").read_bytes() == roadmap
    schema = json.loads((tmp_path / ".roadmap/agent_result.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    envelope = {
        "activity_event": {
            "action": "complete",
            "task_id": "T",
            "prior_status": "in_progress",
            "verification": {"checks": ["a"]},
        },
        "file_updates": [
            {
                "path": "src/video.mkv",
                "binary": {"source": "a" * 64, "size": 3, "sha256": "b" * 64},
            }
        ],
    }
    Draft202012Validator(schema).validate(envelope)
    again = migrate_active_contracts(tmp_path)
    assert again["status"] == "unchanged"
    reverted = revert_active_contracts(tmp_path, result["backup_dir"])
    assert reverted["status"] == "reverted"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == activity


def test_migrate_conflict_on_incompatible_schema(tmp_path):
    _workspace(tmp_path)
    (tmp_path / ".roadmap/agent_result.schema.json").write_text(
        json.dumps({"type": "object", "properties": {}})
    )
    with pytest.raises(ESAAError) as exc:
        migrate_active_contracts(tmp_path)
    assert exc.value.code == "CONTRACT_MIGRATE_CONFLICT"


def test_bootstrap_force_is_not_required_for_schema_migration(tmp_path):
    _workspace(tmp_path)
    _install_legacy(tmp_path)
    policy = (tmp_path / ".roadmap/RUNTIME_POLICY.yaml").read_text()
    migrate_active_contracts(tmp_path)
    assert (tmp_path / ".roadmap/RUNTIME_POLICY.yaml").read_text() == policy
    yaml.safe_load(policy)
