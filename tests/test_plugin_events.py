from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from esaa.contract_migrate import check_contract_drift
from esaa.plugins import (
    activate_roadmap,
    install_plugin,
    list_installed_plugins,
    list_roadmaps,
    remove_plugin,
    scaffold_plugin,
    set_roadmap_status,
    update_plugin,
)
from esaa.service import ESAAService
from esaa.store import parse_event_store


def _run_cli(root: Path, *args: str) -> tuple[int, dict]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "esaa", "--root", str(root), *args],
        env=env,
        text=True,
        capture_output=True,
    )
    data = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"raw": proc.stdout}
    return proc.returncode, data


def test_plugin_and_roadmap_lifecycle_emits_events_and_reconstructs_locks_byte_for_byte(
    contract_bundle: Path,
) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)
    plugin_dir = contract_bundle / "sec-plug"
    scaffold_plugin(contract_bundle, "sec-plug", directory=str(plugin_dir))

    # Dry-run must not emit events or create lock files
    dry = install_plugin(contract_bundle, str(plugin_dir), dry_run=True)
    assert dry["status"] == "dry_run"
    assert not (contract_bundle / ".roadmap" / "plugins.lock.json").exists()
    assert not any(ev["action"].startswith("plugin.") for ev in parse_event_store(contract_bundle))

    # Install + activate + pause + resume + update
    res_install = install_plugin(contract_bundle, str(plugin_dir))
    assert res_install["status"] == "installed"
    res_activate = activate_roadmap(contract_bundle, "sec-plug", execution_id="exec-one")
    assert res_activate["status"] == "active"

    # Eligible reads active roadmap from projected state
    eligible_tasks = svc.eligible()["eligible"]
    assert any(t["task_id"].startswith("sec-plug-exec-one-") for t in eligible_tasks)

    # Dry-run pause/resume/update emit nothing
    seq_before_dry = parse_event_store(contract_bundle)[-1]["event_seq"]
    assert (
        set_roadmap_status(contract_bundle, "sec-plug", "exec-one", "paused", dry_run=True)["status"]
        == "dry_run"
    )
    assert update_plugin(contract_bundle, str(plugin_dir), dry_run=True)["status"] == "dry_run"
    assert parse_event_store(contract_bundle)[-1]["event_seq"] == seq_before_dry

    assert set_roadmap_status(contract_bundle, "sec-plug", "exec-one", "paused")["status"] == "paused"
    assert set_roadmap_status(contract_bundle, "sec-plug", "exec-one", "active")["status"] == "active"
    assert update_plugin(contract_bundle, str(plugin_dir))["action"] == "plugin.update"

    plugins_lock_path = contract_bundle / ".roadmap" / "plugins.lock.json"
    roadmaps_lock_path = contract_bundle / ".roadmap" / "roadmaps.lock.json"
    before_plugins_bytes = plugins_lock_path.read_bytes()
    before_roadmaps_bytes = roadmaps_lock_path.read_bytes()

    # Delete lock files and reconstruct byte-for-byte via `esaa project`
    plugins_lock_path.unlink()
    roadmaps_lock_path.unlink()
    rc, proj = _run_cli(contract_bundle, "project")
    assert rc == 0, proj
    assert plugins_lock_path.read_bytes() == before_plugins_bytes
    assert roadmaps_lock_path.read_bytes() == before_roadmaps_bytes

    # Events have runner stamped
    plugin_events = [
        ev for ev in parse_event_store(contract_bundle) if ev["action"].startswith(("plugin.", "roadmap."))
    ]
    assert [ev["action"] for ev in plugin_events] == [
        "plugin.install",
        "roadmap.activate",
        "roadmap.pause",
        "roadmap.resume",
        "plugin.update",
    ]
    assert all("runner" in ev and ev["runner"] is not None for ev in plugin_events)

    # Remove plugin emits plugin.remove and clears both locks
    assert remove_plugin(contract_bundle, "sec-plug")["removed"] == 1
    assert list_installed_plugins(contract_bundle) == []
    assert list_roadmaps(contract_bundle) == []


def test_legacy_lock_files_read_compatible_and_adopted_on_first_write(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)

    plugin_dir = contract_bundle / "custom-plug"
    scaffold_plugin(contract_bundle, "custom-plug", directory=str(plugin_dir))

    # Simulate legacy workspace with lock files and zero plugin/roadmap events
    (contract_bundle / ".roadmap" / "plugins.lock.json").write_text(
        json.dumps(
            {
                "schema_version": "esaa-plugins-lock/v1",
                "plugins": [
                    {
                        "id": "custom-plug",
                        "name": "custom-plug",
                        "version": "0.1.0",
                        "source": "local",
                        "content_hash": "sha256:legacy",
                        "manifest_path": str(plugin_dir / "plugin.json"),
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (contract_bundle / ".roadmap" / "roadmaps.lock.json").write_text(
        json.dumps(
            {
                "schema_version": "esaa-roadmaps-lock/v1",
                "roadmaps": [
                    {
                        "plugin_id": "custom-plug",
                        "plugin_version": "0.1.0",
                        "execution_id": "legacy-exec",
                        "roadmap": "roadmap.json",
                        "input": None,
                        "content_hash": "sha256:legacy",
                        "status": "paused",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert [p["id"] for p in list_installed_plugins(contract_bundle)] == ["custom-plug"]
    assert [r["execution_id"] for r in list_roadmaps(contract_bundle)] == ["legacy-exec"]
    rc, ver = _run_cli(contract_bundle, "verify")
    assert rc == 0
    assert ver["verify_status"] == "ok"

    # First write adopts legacy state into the event store
    resumed = set_roadmap_status(contract_bundle, "custom-plug", "legacy-exec", "active")
    assert resumed["status"] == "active"
    actions = [
        ev["action"]
        for ev in parse_event_store(contract_bundle)
        if ev["action"].startswith(("plugin.", "roadmap."))
    ]
    assert actions == ["plugin.install", "roadmap.activate", "roadmap.pause", "roadmap.resume"]


def test_contract_set_on_migrate_revert_and_manual_drift_warning(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=False)

    # Record baseline via CLI `esaa contract set`
    rc, dry = _run_cli(contract_bundle, "contract", "set", "--dry-run")
    assert rc == 0
    assert dry["status"] == "dry_run"
    assert not any(ev["action"] == "contract.set" for ev in parse_event_store(contract_bundle))

    rc, recorded = _run_cli(contract_bundle, "contract", "set")
    assert rc == 0
    assert recorded["status"] == "recorded"
    assert any(ev["action"] == "contract.set" for ev in parse_event_store(contract_bundle))

    rc, ver = _run_cli(contract_bundle, "verify")
    assert rc == 0
    assert ver["verify_status"] == "ok"
    assert ver["contract_status"] == "ok"

    # Manual edit triggers informative contract_status="divergent" without failing verify
    ac_path = contract_bundle / ".roadmap" / "AGENT_CONTRACT.yaml"
    ac_path.write_text(ac_path.read_text(encoding="utf-8") + "\n# manual edit\n", encoding="utf-8")
    rc, ver_div = _run_cli(contract_bundle, "verify")
    assert rc == 0
    assert ver_div["verify_status"] == "ok"
    assert ver_div["contract_status"] == "divergent"
    assert any(item["contract"] == "AGENT_CONTRACT.yaml" for item in ver_div["divergent_contracts"])

    # Migrate + revert via CLI emit contract.set when files change
    rc_mig, mig = _run_cli(contract_bundle, "contract", "migrate")
    assert rc_mig == 0
    if mig["status"] == "migrated":
        assert check_contract_drift(contract_bundle)["divergent_contracts"]
        rc_rev, rev = _run_cli(contract_bundle, "contract", "revert", "--from", mig["backup_dir"])
        assert rc_rev == 0
        assert rev["status"] == "reverted"
        contract_events = [ev for ev in parse_event_store(contract_bundle) if ev["action"] == "contract.set"]
        assert any(ev["payload"].get("source") == "contract.migrate" for ev in contract_events)
        assert any(ev["payload"].get("source") == "contract.revert" for ev in contract_events)
