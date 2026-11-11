"""AUD-O0-060 (GOV-05) - comparacao de conteudo entre projecoes armazenadas e replay.

`verify` comparava apenas o campo `projection_hash_sha256` gravado em
roadmap.json com o hash do replay; editar o conteudo de roadmap.json mantendo
esse campo, ou qualquer parte de issues.json / lessons.json, passava como "ok".
Aqui cada projecao armazenada e comparada, por inteiro, com o que o replay
produz.

Unica tolerancia: `meta.updated_at` quando o event store esta vazio. Com
eventos, o campo vem do `ts` do ultimo evento e e deterministico; sem eventos,
o projetor usa o relogio (utc_now) e dois replays nunca coincidem.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .constants import ISSUES_PATH, LESSONS_PATH, ROADMAP_PATH

PROJECTION_FILES: tuple[tuple[str, str], ...] = (
    ("roadmap.json", ROADMAP_PATH),
    ("issues.json", ISSUES_PATH),
    ("lessons.json", LESSONS_PATH),
)
REBUILD_HINT = "stored projections differ from the event-store replay; run `esaa project` to rebuild them"

MISSING = "missing"
UNREADABLE = "unreadable"


def read_projection(path: Path) -> tuple[Any, str | None]:
    """Devolve (conteudo, problema). problema: None, 'missing' ou 'unreadable'."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, MISSING
    except (OSError, UnicodeDecodeError):
        return None, UNREADABLE
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, UNREADABLE


def _comparable(view: Any, ignore_updated_at: bool) -> Any:
    # Round-trip JSON: compara o que seria gravado, nao tipos Python incidentais.
    normalized = json.loads(json.dumps(view, ensure_ascii=False))
    if ignore_updated_at and isinstance(normalized, dict) and isinstance(normalized.get("meta"), dict):
        normalized = deepcopy(normalized)
        normalized["meta"].pop("updated_at", None)
    return normalized


def compare_projections(
    root: Path,
    projected: dict[str, Any],
    *,
    ignore_updated_at: bool = False,
) -> dict[str, Any]:
    """Compara as projecoes em disco com as materializadas.

    `projected` mapeia o nome do arquivo ("roadmap.json", ...) para a view do replay.
    Retorna {"divergent": [nomes], "problems": {nome: missing|unreadable},
    "stored_roadmap": dict|None}. Arquivo ausente ou ilegivel conta como divergente.
    """
    divergent: list[str] = []
    problems: dict[str, str] = {}
    stored_roadmap: dict[str, Any] | None = None
    for name, rel_path in PROJECTION_FILES:
        stored, problem = read_projection(root / rel_path)
        if problem is not None:
            problems[name] = problem
            divergent.append(name)
            continue
        if name == "roadmap.json" and isinstance(stored, dict):
            stored_roadmap = stored
        if _comparable(stored, ignore_updated_at) != _comparable(projected[name], ignore_updated_at):
            divergent.append(name)
    return {"divergent": divergent, "problems": problems, "stored_roadmap": stored_roadmap}
