"""FIX-1809-QA — Verify eligible exposes plugin tasks (run parity gap test).

Esta trilha foi entregue parcialmente: o checker e a API `load_plugin_seeds`
ja existem e `service.eligible` (e o canonical roadmap) consome plugins
ao seed (init). O upgrade completo de `run` para admitir plugins on-the-fly
(sem init) e deferred — documentado em docs/qa/FIX-1809-run-plugin-dispatch.md.

Os testes abaixo cobrem o que esta implementado.
"""
from __future__ import annotations

import json
from pathlib import Path

from esaa.service import ESAAService, load_plugin_seeds


def _make_roadmap_plugin(path: Path, task_id: str, kind: str = "spec") -> None:
    out_file = {"spec": f"docs/spec/{task_id}.md",
                "impl": f"src/{task_id.lower()}.txt",
                "qa": f"docs/qa/{task_id}.md"}[kind]
    data = {
        "meta": {"schema_version": "0.4.1", "esaa_version": "0.4.x",
                 "immutable_done": True, "master_correlation_id": None,
                 "run": {"run_id": None, "status": "initialized",
                          "last_event_seq": 0,
                          "projection_hash_sha256": "0" * 64,
                          "verify_status": "unknown"},
                 "updated_at": "2026-05-23T00:00:00Z"},
        "project": {"name": "test-plugin", "audit_scope": "x"},
        "tasks": [{"task_id": task_id, "task_kind": kind,
                    "title": task_id, "description": task_id,
                    "status": "todo", "depends_on": [], "targets": [],
                    "outputs": {"files": [out_file]},
                    "immutability": {"done_is_immutable": True}}],
        "indexes": {"by_status": {"todo": 1}, "by_kind": {kind: 1}},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_plugin_seeds_finds_plugin(tmp_path: Path) -> None:
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    _make_roadmap_plugin(rm / "roadmap.demo.json", "DEMO-1", "spec")
    seed = load_plugin_seeds(tmp_path)
    assert seed is not None
    assert seed["tasks"][0]["task_id"] == "DEMO-1"


def test_init_seeds_plugin_tasks(tmp_path: Path) -> None:
    """init() com plugins admite as tasks via task.create."""
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    # copia contratos minimos do canonical
    import shutil
    src_root = Path(__file__).resolve().parents[1]
    for fname in ("AGENT_CONTRACT.yaml", "ORCHESTRATOR_CONTRACT.yaml",
                  "agent_result.schema.json", "roadmap.schema.json",
                  "issues.schema.json", "lessons.schema.json"):
        shutil.copy(src_root / ".roadmap" / fname, rm / fname)
    _make_roadmap_plugin(rm / "roadmap.demo.json", "PLG-1", "spec")
    _make_roadmap_plugin(rm / "roadmap.beta.json", "PLG-2", "spec")

    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)

    roadmap = json.loads((rm / "roadmap.json").read_text(encoding="utf-8"))
    ids = {t["task_id"] for t in roadmap["tasks"]}
    assert {"PLG-1", "PLG-2"}.issubset(ids)


def test_eligible_lists_plugin_tasks(tmp_path: Path) -> None:
    """service.eligible exibe tarefas todo cujas deps sao done."""
    rm = tmp_path / ".roadmap"
    rm.mkdir()
    import shutil
    src_root = Path(__file__).resolve().parents[1]
    for fname in ("AGENT_CONTRACT.yaml", "ORCHESTRATOR_CONTRACT.yaml",
                  "agent_result.schema.json", "roadmap.schema.json",
                  "issues.schema.json", "lessons.schema.json"):
        shutil.copy(src_root / ".roadmap" / fname, rm / fname)
    _make_roadmap_plugin(rm / "roadmap.demo.json", "ELIG-1", "spec")

    svc = ESAAService(tmp_path)
    svc.init(force=True, with_demo_tasks=True)
    elig = svc.eligible()
    ids = {t["task_id"] for t in elig["eligible"]}
    assert "ELIG-1" in ids
