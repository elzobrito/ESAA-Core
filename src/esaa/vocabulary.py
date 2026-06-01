from __future__ import annotations

from typing import Any


VOCABULARY_ROWS: list[dict[str, Any]] = [
    {"profile": "paper-v0.3", "term": "promote", "kind": "action", "status": "historical", "maps_to": "claim", "note": "phase promotion before the v0.4 two-step contract"},
    {"profile": "paper-v0.3", "term": "phase.complete", "kind": "action", "status": "historical", "maps_to": "complete", "note": "phase-gated naming collapsed into complete"},
    {"profile": "paper-v0.3", "term": "backlog", "kind": "task_status", "status": "historical", "maps_to": "todo", "note": "planning queue in early vocabulary"},
    {"profile": "paper-v0.3", "term": "ready", "kind": "task_status", "status": "historical", "maps_to": "todo", "note": "eligible work before canonical todo"},
    {"profile": "clinic-asr", "term": "backlog", "kind": "task_status", "status": "profile-specific", "maps_to": "todo", "note": "simplified clinical workflow profile"},
    {"profile": "clinic-asr", "term": "ready", "kind": "task_status", "status": "profile-specific", "maps_to": "todo", "note": "profile-level queue state"},
    {"profile": "core-v0.4.1", "term": "claim", "kind": "action", "status": "canonical", "maps_to": None, "note": "todo -> in_progress"},
    {"profile": "core-v0.4.1", "term": "complete", "kind": "action", "status": "canonical", "maps_to": None, "note": "in_progress -> review"},
    {"profile": "core-v0.4.1", "term": "review", "kind": "action", "status": "canonical", "maps_to": None, "note": "review approve -> done or request_changes -> in_progress"},
    {"profile": "core-v0.4.1", "term": "issue.report", "kind": "action", "status": "canonical", "maps_to": None, "note": "fail-closed issue path"},
    {"profile": "core-v0.4.1", "term": "plugin.install", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "install plugin package into workspace lock"},
    {"profile": "core-v0.4.1", "term": "plugin.remove", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "remove installed plugin from workspace lock"},
    {"profile": "core-v0.4.1", "term": "plugin.update", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "update installed plugin version"},
    {"profile": "core-v0.4.1", "term": "roadmap.activate", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "activate an installed plugin roadmap execution"},
    {"profile": "core-v0.4.1", "term": "roadmap.pause", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "hide an active roadmap execution from eligibility"},
    {"profile": "core-v0.4.1", "term": "roadmap.resume", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "restore a paused roadmap execution to eligibility"},
    {"profile": "core-v0.4.1", "term": "roadmap.deactivate", "kind": "reserved_orchestrator_action", "status": "canonical", "maps_to": None, "note": "remove a roadmap execution from future planned work"},
    {"profile": "core-v0.4.1", "term": "todo", "kind": "task_status", "status": "canonical", "maps_to": None, "note": "initial executable state"},
    {"profile": "core-v0.4.1", "term": "in_progress", "kind": "task_status", "status": "canonical", "maps_to": None, "note": "claimed and locked"},
    {"profile": "core-v0.4.1", "term": "review", "kind": "task_status", "status": "canonical", "maps_to": None, "note": "awaiting QA decision"},
    {"profile": "core-v0.4.1", "term": "done", "kind": "task_status", "status": "canonical", "maps_to": None, "note": "terminal and immutable"},
]


def vocabulary_table(profile: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(row) for row in VOCABULARY_ROWS]
    if profile:
        rows = [row for row in rows if row["profile"] == profile]
    return rows


def vocabulary_payload(profile: str | None = None) -> dict[str, Any]:
    rows = vocabulary_table(profile)
    profiles = sorted({row["profile"] for row in VOCABULARY_ROWS})
    return {
        "canonical_profile": "core-v0.4.1",
        "profiles": profiles,
        "rows": rows,
        "read_only": True,
    }

