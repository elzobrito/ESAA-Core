"""FIX-1562 — Loader generico de plugins (R9)."""
from __future__ import annotations
import json
from pathlib import Path

from esaa.service import ESAAService, load_plugin_seeds
from esaa.store import parse_event_store


def _make_roadmap(tasks):
    return {
        "meta": {"schema_version": "0.4.0", "esaa_version": "0.4.x", "immutable_done": True,
                 "master_correlation_id": None,
                 "run": {"run_id": None, "status": "initialized", "last_event_seq": 0,
                          "projection_hash_sha256": "0" * 64, "verify_status": "unknown"},
                 "updated_at": "2026-05-23T00:00:00Z"},
        "project": {"name": "p", "audit_scope": "x"},
        "tasks": tasks,
        "indexes": {"by_status": {"todo": len(tasks)}, "by_kind": {"spec": len(tasks)}},
    }


def _task(tid, kind="spec"):
    return {"task_id": tid, "task_kind": kind, "title": tid, "description": tid,
            "status": "todo", "depends_on": [], "targets": [],
            "outputs": {"files": [f"docs/spec/{tid}.md"]},
            "immutability": {"done_is_immutable": True}}


def test_loader_unions_two_plugins(tmp_path):
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    (rm / "roadmap.alpha.json").write_text(json.dumps(_make_roadmap([_task("X-1")])), encoding="utf-8")
    (rm / "roadmap.beta.json").write_text(json.dumps(_make_roadmap([_task("X-2"), _task("X-3")])), encoding="utf-8")
    seed = load_plugin_seeds(tmp_path)
    assert seed is not None
    ids = sorted(t["task_id"] for t in seed["tasks"])
    assert ids == ["X-1", "X-2", "X-3"]


def test_loader_dedupes_by_task_id(tmp_path):
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    (rm / "roadmap.alpha.json").write_text(json.dumps(_make_roadmap([_task("X-1")])), encoding="utf-8")
    (rm / "roadmap.beta.json").write_text(json.dumps(_make_roadmap([_task("X-1"), _task("X-2")])), encoding="utf-8")
    seed = load_plugin_seeds(tmp_path)
    assert sorted(t["task_id"] for t in seed["tasks"]) == ["X-1", "X-2"]


def test_loader_returns_none_without_plugins(tmp_path):
    (tmp_path / ".roadmap").mkdir()
    assert load_plugin_seeds(tmp_path) is None


def test_loader_ignores_roadmap_json(tmp_path):
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    (rm / "roadmap.json").write_text(json.dumps(_make_roadmap([_task("X-1")])), encoding="utf-8")
    # so 'roadmap.json' presente — sem plugins -> None
    assert load_plugin_seeds(tmp_path) is None


def test_loader_ignores_template_roadmap_files(tmp_path):
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    (rm / "roadmap.demo.template.json").write_text(json.dumps(_make_roadmap([_task("X-1")])), encoding="utf-8")

    assert load_plugin_seeds(tmp_path) is None


def test_loader_uses_active_installed_plugin_tasks(tmp_path: Path, repo_root: Path):
    from esaa.plugins import activate_roadmap, install_plugin, scaffold_plugin

    service = ESAAService(tmp_path)
    service.init(force=True)

    scaffold_plugin(tmp_path, "sso-client", repo_root=repo_root)
    install_plugin(tmp_path, "./sso-client", repo_root=repo_root)
    activate_roadmap(tmp_path, "sso-client", execution_id="default", repo_root=repo_root)

    seed = load_plugin_seeds(tmp_path)

    assert seed is not None
    ids = [task["task_id"] for task in seed["tasks"]]
    assert "sso-client-default-T-001" in ids


def test_eligible_includes_planned_plugin_tasks_without_task_create(tmp_path):
    service = ESAAService(tmp_path)
    service.init(force=True)

    rm = tmp_path / ".roadmap"
    (rm / "roadmap.opt.json").write_text(
        json.dumps(_make_roadmap([_task("OPT-1"), _task("OPT-2")])),
        encoding="utf-8",
    )

    result = service.eligible()

    assert [task["task_id"] for task in result["eligible"]] == ["OPT-1", "OPT-2", "T-1000"]
    assert all(task["source"] in {"event_store", "roadmap_plugin"} for task in result["eligible"])
    assert not any(
        event["action"] == "task.create" and event["payload"].get("task_id") == "OPT-1"
        for event in parse_event_store(tmp_path)
    )


def test_claim_admits_planned_plugin_task_before_transition(contract_bundle: Path):
    service = ESAAService(contract_bundle)
    service.init(force=True)

    rm = contract_bundle / ".roadmap"
    (rm / "roadmap.opt.json").write_text(
        json.dumps(_make_roadmap([_task("OPT-1")])),
        encoding="utf-8",
    )

    result = service.claim_task("OPT-1", actor="agent-spec")

    assert result["action"] == "claim"
    assert result["task"]["status"] == "in_progress"
    events = [
        event for event in parse_event_store(contract_bundle)
        if event["payload"].get("task_id") == "OPT-1"
    ]
    assert [event["action"] for event in events] == ["task.create", "claim"]
