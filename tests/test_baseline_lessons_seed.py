"""FIX-1813-QA — Baseline lessons reseed."""
from __future__ import annotations

import json
from pathlib import Path

from esaa.projector import materialize
from esaa.service import BASELINE_LESSONS, ESAAService
from esaa.store import parse_event_store


def test_baseline_lessons_constant_has_three_lessons() -> None:
    ids = {l["lesson_id"] for l in BASELINE_LESSONS}
    assert ids == {"LES-0001", "LES-0002", "LES-0003"}


def test_baseline_lessons_have_required_fields() -> None:
    for lesson in BASELINE_LESSONS:
        for key in ("lesson_id", "status", "title", "rule", "scope", "enforcement"):
            assert key in lesson
        assert lesson["status"] == "active"


def test_init_appends_baseline_lessons_event(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    matching = [
        e for e in events
        if e["action"] == "orchestrator.view.mutate"
        and (e.get("payload") or {}).get("target") == "lessons"
        and "lessons" in (e.get("payload") or {})
    ]
    assert len(matching) >= 1
    lessons = matching[0]["payload"]["lessons"]
    ids = {l["lesson_id"] for l in lessons}
    assert ids == {"LES-0001", "LES-0002", "LES-0003"}


def test_lessons_json_has_three_active_lessons_after_init(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    data = json.loads((contract_bundle / ".roadmap" / "lessons.json").read_text(encoding="utf-8"))
    lessons = data.get("lessons", [])
    assert len(lessons) >= 3
    ids = {l["lesson_id"] for l in lessons}
    assert {"LES-0001", "LES-0002", "LES-0003"}.issubset(ids)
    for l in lessons:
        if l["lesson_id"] in {"LES-0001", "LES-0002", "LES-0003"}:
            assert l.get("status") == "active"


def test_lessons_survive_clean_replay(contract_bundle: Path) -> None:
    """Replay determinístico reproduz lessons identicamente."""
    svc = ESAAService(contract_bundle)
    svc.init(force=True, with_demo_tasks=True)
    events = parse_event_store(contract_bundle)
    _, _, lessons_view = materialize(events)
    ids = {l["lesson_id"] for l in lessons_view["lessons"]}
    assert {"LES-0001", "LES-0002", "LES-0003"}.issubset(ids)
