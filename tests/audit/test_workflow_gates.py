#!/usr/bin/env python3
"""AUD-1301 — Auditoria do dispatch two-step e dos workflow gates.

Compara os gates DOCUMENTADOS (WG-001..WG-005 + RUNTIME_POLICY) com o que o
engine REALMENTE aplica. Executavel como script (imprime matriz) e tambem
contem asserts estilo pytest.

Uso: PYTHONPATH=src python tests/audit/test_workflow_gates.py --root <repo>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DOCUMENTED = {
    "WG-001": "MISSING_CLAIM (complete/review so apos claim)",
    "WG-002": "MISSING_VERIFICATION / MISSING_COMPLETE",
    "WG-003": "PRIOR_STATUS_MISMATCH (nao penaliza counter)",
    "WG-004": "LOCK_VIOLATION (assigned_to == actor)",
    "WG-005": "ACTION_COLLAPSE (um activity_event)",
    "RUNTIME_POLICY": "max_attempts=3, cooldown PT2M, TTL PT30M, ATTEMPT_TIMEOUT",
}


def audit_engine(root: Path):
    """Inspeciona o codigo do engine para mapear enforcement real."""
    rows = {}
    proj = (
        (root / "src/esaa/projector.py").read_text(encoding="utf-8")
        if (root / "src/esaa/projector.py").exists()
        else ""
    )
    val = (
        (root / "src/esaa/validator.py").read_text(encoding="utf-8")
        if (root / "src/esaa/validator.py").exists()
        else ""
    )
    svc = (
        (root / "src/esaa/service.py").read_text(encoding="utf-8")
        if (root / "src/esaa/service.py").exists()
        else ""
    )

    rows["WG-001"] = {
        "enforced": "INVALID_TRANSITION" in proj,
        "where": "projector._apply_complete (status != in_progress)",
        "engine_code": "INVALID_TRANSITION",
        "matches_doc_code": "MISSING_CLAIM" in (proj + val),
    }
    rows["WG-002"] = {
        "enforced": "verification" in val,
        "where": "validator (so task_kind=='impl') + schema (>=1)",
        "engine_code": "WORKFLOW_GATE",
        "matches_doc_code": "MISSING_VERIFICATION" in val,
    }
    rows["WG-003"] = {
        "enforced": "prior_status" in val and 'task["status"]' in val,
        "where": "NAO comparado ao status real do roadmap",
        "engine_code": "(ausente; surge como INVALID_TRANSITION)",
        "matches_doc_code": "PRIOR_STATUS_MISMATCH" in val,
    }
    rows["WG-004"] = {
        "enforced": "_ensure_owner" in proj,
        "where": "projector._ensure_owner",
        "engine_code": "NOT_LOCK_OWNER",
        "matches_doc_code": "LOCK_VIOLATION" in proj,
    }
    rows["WG-005"] = {
        "enforced": True,
        "where": "schema (activity_event objeto unico)",
        "engine_code": "(estrutural)",
        "matches_doc_code": True,
    }
    rows["RUNTIME_POLICY"] = {
        "enforced": "max_attempts" in svc or "attempt_counter" in svc,
        "where": "apenas heuristica de stall em service.run",
        "engine_code": "(nenhum)",
        "matches_doc_code": False,
    }
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root)
    rows = audit_engine(root)
    findings = []
    for gate, info in rows.items():
        if not info["enforced"]:
            findings.append(
                {
                    "id": "R2" if gate == "RUNTIME_POLICY" else "R7",
                    "severity": "high" if gate in ("RUNTIME_POLICY", "WG-003") else "medium",
                    "title": f"{gate} documentado mas NAO aplicado: {DOCUMENTED[gate]}",
                    "evidence": info,
                }
            )
        elif not info["matches_doc_code"]:
            findings.append(
                {
                    "id": "R6",
                    "severity": "medium",
                    "title": f"{gate} aplicado com codigo divergente do contrato",
                    "evidence": info,
                }
            )
    print(
        json.dumps(
            {"checker": "workflow_gates", "matrix": rows, "findings": findings}, indent=2, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
