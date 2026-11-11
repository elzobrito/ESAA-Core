"""M-04 inventory test — todo ESAAError(<code>, ...) em src/esaa/*.py deve
estar registrado em src/esaa/reject_codes.py#ALL_CODES.

Garante fonte unica de verdade do vocabulario de reject codes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from esaa import reject_codes

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "src" / "esaa"


def _iter_engine_files() -> Iterator[Path]:
    for path in ENGINE_DIR.rglob("*.py"):
        # ignora __pycache__ e o proprio reject_codes
        if "__pycache__" in path.parts:
            continue
        if path.name == "reject_codes.py":
            continue
        yield path


def _extract_esaa_error_codes(source: str) -> list[tuple[str, int]]:
    """Retorna list of (code_string, line) usadas em raise ESAAError(<code>, ...)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name not in {"ESAAError", "CorruptedStoreError"}:
            continue
        if not node.args:
            continue
        first = node.args[0]
        # Literal string
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append((first.value, first.lineno))
        # Expressao tipo (code or "FOO") — extrai fallback literal
        elif isinstance(first, ast.BoolOp):
            for value in first.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.append((value.value, value.lineno))
    return out


def test_all_emitted_codes_are_registered() -> None:
    """Cada string passada como primeiro arg de ESAAError() deve estar em ALL_CODES."""
    orphans: list[tuple[str, str, int]] = []
    for path in _iter_engine_files():
        source = path.read_text(encoding="utf-8")
        for code, lineno in _extract_esaa_error_codes(source):
            if code not in reject_codes.ALL_CODES:
                orphans.append((str(path.relative_to(REPO_ROOT)), code, lineno))
    assert (
        not orphans
    ), "Codigos emitidos via ESAAError nao registrados em reject_codes.ALL_CODES:\n" + "\n".join(
        f"  {p}:{ln}  {c}" for p, c, ln in orphans
    )


def test_workflow_gate_codes_are_subset_of_all() -> None:
    assert reject_codes.WORKFLOW_GATE_CODES <= reject_codes.ALL_CODES


def test_operational_codes_are_subset_of_all() -> None:
    assert reject_codes.OPERATIONAL_CODES <= reject_codes.ALL_CODES


def test_hotfix_codes_are_subset_of_all() -> None:
    assert reject_codes.HOTFIX_CODES <= reject_codes.ALL_CODES


def test_families_are_disjoint() -> None:
    assert reject_codes.WORKFLOW_GATE_CODES.isdisjoint(reject_codes.OPERATIONAL_CODES)
    assert reject_codes.WORKFLOW_GATE_CODES.isdisjoint(reject_codes.HOTFIX_CODES)
    assert reject_codes.OPERATIONAL_CODES.isdisjoint(reject_codes.HOTFIX_CODES)


def test_state_machine_aliases_resolve() -> None:
    from esaa import state_machine

    assert state_machine.REJECT_MISSING_CLAIM == reject_codes.MISSING_CLAIM
    assert state_machine.REJECT_IMMUTABLE_DONE == reject_codes.IMMUTABLE_DONE_VIOLATION
    assert state_machine.REJECT_LOCK == reject_codes.LOCK_VIOLATION
    assert state_machine.REJECT_PRIOR_MISMATCH == reject_codes.PRIOR_STATUS_MISMATCH


def test_all_codes_is_at_least_30() -> None:
    """Garantia mínima de cobertura — protege contra deleções acidentais."""
    assert len(reject_codes.ALL_CODES) >= 30, f"Esperado >= 30 codes, got {len(reject_codes.ALL_CODES)}"
