"""QA do boundary_grant por tarefa (T-2072; spec em docs/spec/T-2070-boundary-grant.md).

Cobre os 5 criterios de aceite: persistencia no payload/projecao/dispatch,
enforcement como alternativa a allowlist do kind, precedencia de
forbidden_write sobre o grant, validacao de padroes na criacao e replay
deterministico.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.file_effects import STAGING_DIR
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def grant_bundle(contract_bundle: Path) -> Path:
    # Estado pos-rollout: o schema vivo do bundle sincronizado com o template
    # que declara a propriedade opcional boundary_grant.
    shutil.copy2(
        REPO_ROOT / "src" / "esaa" / "templates" / "roadmap.schema.json",
        contract_bundle / ".roadmap" / "roadmap.schema.json",
    )
    return contract_bundle


def _service(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True, with_demo_tasks=True)
    return svc


def _create_granted_task(svc: ESAAService, task_id: str = "T-GR-1") -> None:
    svc.create_task(
        task_id,
        task_kind="impl",
        title="task com grant de tools/audit",
        boundary_grant=["tools/audit/**"],
    )


def _claim(svc: ESAAService, task_id: str, actor: str = "agent-impl") -> None:
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": task_id, "prior_status": "todo"}},
        actor=actor,
    )


def _complete_with(task_id: str, updates: list[dict]) -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": task_id,
            "prior_status": "in_progress",
            "verification": {"checks": ["boundary grant validado"]},
        },
        "file_updates": updates,
    }


def _staging_files(root: Path) -> list[Path]:
    staging = root / STAGING_DIR
    if not staging.exists():
        return []
    return [path for path in staging.rglob("*") if path.is_file()]


# ---------------------------------------------------------------------------
# Criterio 1 — payload, projecao e dispatch-context
# ---------------------------------------------------------------------------


def test_grant_recorded_in_event_payload_projection_and_dispatch(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    _create_granted_task(svc)

    create_events = [
        e
        for e in parse_event_store(grant_bundle)
        if e["action"] == "task.create" and e["payload"].get("task_id") == "T-GR-1"
    ]
    assert len(create_events) == 1
    assert create_events[0]["payload"]["boundary_grant"] == ["tools/audit/**"]

    task = svc.task_state("T-GR-1")["task"]
    assert task["boundary_grant"] == ["tools/audit/**"]

    ctx = svc.dispatch_context("T-GR-1")
    assert ctx["task"]["boundary_grant"] == ["tools/audit/**"]


# ---------------------------------------------------------------------------
# Criterio 2 — enforcement: aceito com grant, rejeitado sem grant
# ---------------------------------------------------------------------------


def test_complete_outside_kind_allowlist_accepted_with_grant(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    _create_granted_task(svc)
    _claim(svc, "T-GR-1")

    result = svc.submit(
        _complete_with("T-GR-1", [{"path": "tools/audit/extra_check.py", "content": "ok = True\n"}]),
        actor="agent-impl",
    )

    assert result["status"] == "accepted"
    assert result["files_written"] == 1
    assert (grant_bundle / "tools/audit/extra_check.py").read_text(encoding="utf-8") == "ok = True\n"


def test_complete_outside_kind_allowlist_rejected_without_grant(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    svc.create_task("T-NG-1", task_kind="impl", title="task sem grant")
    _claim(svc, "T-NG-1")
    before = len(parse_event_store(grant_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with("T-NG-1", [{"path": "tools/audit/evil.py", "content": "x\n"}]),
            actor="agent-impl",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert not (grant_bundle / "tools/audit/evil.py").exists()
    assert len(parse_event_store(grant_bundle)) == before
    assert _staging_files(grant_bundle) == []


def test_grant_is_per_task_not_per_store(grant_bundle: Path) -> None:
    # O grant de T-GR-1 nao vaza para outra task do mesmo store.
    svc = _service(grant_bundle)
    _create_granted_task(svc)
    svc.create_task("T-NG-2", task_kind="impl", title="vizinha sem grant")
    _claim(svc, "T-NG-2")

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with("T-NG-2", [{"path": "tools/audit/extra_check.py", "content": "x\n"}]),
            actor="agent-impl",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"


def test_grant_does_not_authorize_runtime_paths(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    svc.create_task(
        "T-GR-RT", task_kind="impl", title="grant amplo", boundary_grant=["**"]
    )
    _claim(svc, "T-GR-RT")

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with("T-GR-RT", [{"path": "runtime://outputs.client", "content": "x\n"}]),
            actor="agent-impl",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"


# ---------------------------------------------------------------------------
# Criterio 3 — forbidden_write prevalece sobre o grant
# ---------------------------------------------------------------------------


def test_forbidden_write_prevails_over_broad_grant(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    svc.create_task(
        "T-GR-BROAD", task_kind="impl", title="grant amplo", boundary_grant=["**"]
    )
    _claim(svc, "T-GR-BROAD")

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with("T-GR-BROAD", [{"path": ".roadmap/evil.md", "content": "x\n"}]),
            actor="agent-impl",
        )

    assert exc.value.code == "BOUNDARY_VIOLATION"
    assert not (grant_bundle / ".roadmap/evil.md").exists()


# ---------------------------------------------------------------------------
# Criterio 4 — validacao de padroes na criacao
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    ["", "  ", "../fora", "a/../b", "runtime://outputs.client", "/absoluto", ".roadmap/**", ".roadmap"],
)
def test_invalid_grant_patterns_rejected_at_create_without_events(
    grant_bundle: Path, pattern: str
) -> None:
    svc = _service(grant_bundle)
    before = len(parse_event_store(grant_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.create_task(
            "T-GR-BAD", task_kind="impl", title="grant invalido", boundary_grant=[pattern]
        )

    assert exc.value.code == "SCHEMA_INVALID"
    assert len(parse_event_store(grant_bundle)) == before


def test_grant_patterns_normalized_on_create(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    svc.create_task(
        "T-GR-NORM",
        task_kind="impl",
        title="grant com separador windows",
        boundary_grant=["tools\\audit\\**"],
    )

    task = svc.task_state("T-GR-NORM")["task"]
    assert task["boundary_grant"] == ["tools/audit/**"]


# ---------------------------------------------------------------------------
# Criterio 5 — replay deterministico e verify apos uso do grant
# ---------------------------------------------------------------------------


def test_replay_deterministic_after_grant_usage(grant_bundle: Path) -> None:
    svc = _service(grant_bundle)
    _create_granted_task(svc)
    _claim(svc, "T-GR-1")
    svc.submit(
        _complete_with("T-GR-1", [{"path": "tools/audit/extra_check.py", "content": "ok = True\n"}]),
        actor="agent-impl",
    )

    events = parse_event_store(grant_bundle)
    first = materialize(events)[0]
    second = materialize(events)[0]

    assert (
        first["meta"]["run"]["projection_hash_sha256"]
        == second["meta"]["run"]["projection_hash_sha256"]
    )
    granted = [t for t in first["tasks"] if t["task_id"] == "T-GR-1"]
    assert granted[0]["boundary_grant"] == ["tools/audit/**"]
    assert svc.verify()["verify_status"] == "ok"
