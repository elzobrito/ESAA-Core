"""AUD-O0-030 (SEC-01) - curadoria de lessons propostas por agentes.

Uma lesson criada por `issue.report` de agente nasce `proposed` e fica fora do
dispatch-context. O operador decide: `approve` -> `active`, `reject` -> `archived`.
A decisao e um evento `orchestrator.view.mutate` (change=lesson_status), portanto
reconstruivel por replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import ESAAError
from .events import make_event
from .projector import materialize
from .reject_codes import LESSON_NOT_FOUND, LESSON_NOT_PROPOSED
from .store import next_event_seq, parse_event_store

if TYPE_CHECKING:
    from pathlib import Path

LESSON_DECISIONS = {"approve": "active", "reject": "archived"}


def apply_lesson_status(lessons: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """Aplica uma decisao de curadoria sobre a lista de lessons (usado pelo projetor)."""
    lesson_id = str(payload.get("lesson_id") or "").strip()
    status = payload.get("status")
    if status not in set(LESSON_DECISIONS.values()):
        raise ESAAError("SCHEMA_INVALID", f"invalid lesson status transition: {status}")
    for lesson in lessons:
        if lesson.get("lesson_id") != lesson_id:
            continue
        if lesson.get("status") != "proposed":
            raise ESAAError(
                LESSON_NOT_PROPOSED,
                f"lesson {lesson_id} status={lesson.get('status')}; only proposed lessons can be decided",
            )
        lesson["status"] = status
        return
    raise ESAAError(LESSON_NOT_FOUND, f"lesson not found: {lesson_id}")


class LessonAdminMixin:
    if TYPE_CHECKING:
        root: Path

        def _commit_orchestrator_events(
            self,
            candidate_events: list[dict[str, Any]],
            dry_run: bool = False,
            precommit: Any = None,
            postcommit: Any = None,
        ) -> dict[str, Any]: ...

    def list_lessons(self, status: str | None = None) -> dict[str, Any]:
        """Somente leitura: lessons materializadas do event store, opcionalmente por status."""
        _, _, lessons_view = materialize(parse_event_store(self.root))
        lessons = [
            lesson for lesson in lessons_view["lessons"] if status is None or lesson.get("status") == status
        ]
        return {"lessons": lessons, "total": len(lessons), "filters": {"status": status}}

    def decide_lesson(
        self,
        lesson_id: str,
        decision: str,
        *,
        reason: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Operador aprova ou rejeita uma lesson proposta."""
        if decision not in LESSON_DECISIONS:
            raise ESAAError("INVALID_ARGUMENT", f"lesson decision must be one of {sorted(LESSON_DECISIONS)}")
        if not isinstance(reason, str) or not reason.strip():
            raise ESAAError("INVALID_ARGUMENT", "lesson decision requires a reason")
        events = parse_event_store(self.root)
        payload = {
            "target": "lessons",
            "change": "lesson_status",
            "lesson_id": lesson_id.strip(),
            "status": LESSON_DECISIONS[decision],
            "decision": decision,
            "reason": reason.strip(),
        }
        _, _, lessons_view = materialize(events)
        apply_lesson_status(lessons_view["lessons"], payload)  # falha cedo, antes de montar o evento
        event = make_event(
            next_event_seq(events), actor="orchestrator", action="orchestrator.view.mutate", payload=payload
        )
        result = self._commit_orchestrator_events([event], dry_run=dry_run)
        result.update({"lesson_id": payload["lesson_id"], "lesson_status": payload["status"]})
        return result
