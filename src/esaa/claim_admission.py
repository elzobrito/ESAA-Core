"""AUD-O0-010 (GOV-02) - admissao de claim: dependencias e supersedencia."""

from __future__ import annotations

from typing import Any

from .errors import ESAAError
from .reject_codes import DEPENDENCY_NOT_DONE, TASK_SUPERSEDED


def assert_claim_admissible(tasks: list[dict[str, Any]], task: dict[str, Any]) -> None:
    """AUD-O0-010 (GOV-02): claim so e admitido com dependencias done e sem superseded_by.

    Aplicado na admissao (antes do append), nunca no replay: claims historicos
    aceitos por runtimes anteriores continuam reprojetando sem alteracao.
    Usa o mesmo criterio de `list_eligible_tasks`: dependencia desconhecida
    conta como pendente. Rejeicao nao penaliza o contador de tentativas, pois
    a tarefa apenas ainda nao esta elegivel.
    """
    superseded_by = [str(item) for item in task.get("superseded_by", []) or []]
    if superseded_by:
        raise ESAAError(
            TASK_SUPERSEDED,
            f"task {task['task_id']} is superseded by: {', '.join(sorted(superseded_by))}",
            penalizes_counter=False,
        )
    status_by_id = {item["task_id"]: item.get("status") for item in tasks}
    pending = [
        f"{dep}={status_by_id.get(dep, 'unknown')}"
        for dep in task.get("depends_on", []) or []
        if status_by_id.get(dep) != "done"
    ]
    if pending:
        raise ESAAError(
            DEPENDENCY_NOT_DONE,
            f"task {task['task_id']} has unmet dependencies: {', '.join(pending)}",
            penalizes_counter=False,
        )
