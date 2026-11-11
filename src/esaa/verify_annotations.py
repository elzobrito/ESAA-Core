"""AUD-O1-030 (GOV-07) - anotacoes informativas da resposta de verify.

Nada aqui muda `verify_status`. A cadeia de hash sem ancora e o padrao por
decisao de arquitetura; `chain_status` apenas torna esse estado visivel:

- "unanchored": nao ha evento chain.anchor (padrao);
- "ok": ha ancora e a cadeia foi validada pelo parser nesta leitura.

Um log com cadeia quebrada nao chega aqui: o parser ja o reporta como
`corrupted` (CHAIN_BROKEN).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .boundary_paths import legacy_scope_warnings

TS_REGRESSION_CODE = "EVENT_TS_REGRESSION"


def chain_status(events: list[dict[str, Any]]) -> str:
    return "ok" if any(event.get("action") == "chain.anchor" for event in events) else "unanchored"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def ts_regression_warning(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Um unico aviso agregado quando algum evento tem ts anterior ao do evento precedente.

    Relogios de runners diferentes podem divergir, por isso e aviso e nao erro.
    Eventos sem ts interpretavel sao ignorados na comparacao.
    """
    previous: datetime | None = None
    count = 0
    first_seq: Any = None
    for event in events:
        current = _parse_ts(event.get("ts"))
        if current is None:
            continue
        try:
            regressed = previous is not None and current < previous
        except TypeError:  # mistura de ts com e sem fuso: nao comparavel, ignora o evento
            continue
        if regressed:
            count += 1
            if first_seq is None:
                first_seq = event.get("event_seq")
        else:
            previous = current
    if not count:
        return None
    return {
        "code": TS_REGRESSION_CODE,
        "count": count,
        "first_event_seq": first_seq,
        "message": "event timestamps go backwards; clocks of different runners may differ",
    }


def verify_annotations(events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Campos extras da resposta ok de verify: chain_status e warnings (se houver)."""
    warnings = list(legacy_scope_warnings(tasks).get("warnings", []))
    regression = ts_regression_warning(events)
    if regression:
        warnings.append(regression)
    out: dict[str, Any] = {"chain_status": chain_status(events)}
    if warnings:
        out["warnings"] = warnings
    return out
