from __future__ import annotations

import json
from pathlib import Path

from esaa.service import ESAAService
from esaa.store import parse_event_store


def test_run_parallel_claims_first_eligible_parallel_group(contract_bundle: Path) -> None:
    plugin = {
        "project": {"name": "parallel-test"},
        "tasks": [
            {
                "task_id": "P-1",
                "task_kind": "spec",
                "title": "Parallel 1",
                "depends_on": [],
                "targets": [],
                "outputs": {"files": ["docs/spec/P-1.md"]},
            },
            {
                "task_id": "P-2",
                "task_kind": "spec",
                "title": "Parallel 2",
                "depends_on": [],
                "targets": [],
                "outputs": {"files": ["docs/spec/P-2.md"]},
            },
        ],
    }
    (contract_bundle / ".roadmap" / "roadmap.parallel.json").write_text(
        json.dumps(plugin),
        encoding="utf-8",
    )
    service = ESAAService(contract_bundle)
    service.init(force=True, with_demo_tasks=True)

    result = service.run(steps=1, parallel=2)

    assert result["steps_executed"] == 2
    events = parse_event_store(contract_bundle)
    claims = [event for event in events if event["action"] == "claim"]
    assert [event["payload"]["task_id"] for event in claims] == ["P-1", "P-2"]

