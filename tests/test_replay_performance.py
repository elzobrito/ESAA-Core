"""AUD-O1-010 (ARQ-01) - replay sem custo quadratico.

Dois tipos de teste:
- equivalencia: aplicar eventos de forma incremental sobre um estado ja reproduzido
  produz exatamente as mesmas projecoes que o replay completo, e o servico grava as
  mesmas projecoes que um replay do zero;
- guarda de escala: limites de tempo folgados, apenas para acusar a volta de um custo
  quadratico. Nao sao benchmark.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import esaa.store as store
from esaa.errors import CorruptedStoreError, ESAAError
from esaa.events import make_event
from esaa.identity_history import _has_identity_material, validate_identity_history
from esaa.projector import (
    apply_events,
    finalize_views,
    materialize,
    projection_summary,
    replay_state,
    state_tasks,
)
from esaa.service import ESAAService
from esaa.store import append_events, next_event_seq, parse_event_store


def _lesson_report(issue_id: str, rule: str) -> dict[str, Any]:
    return {
        "activity_event": {
            "action": "issue.report",
            "task_id": "T-A",
            "prior_status": "done",
            "issue_id": issue_id,
            "severity": "low",
            "title": "licao",
            "category": "process",
            "subtype": "lesson",
            "evidence": {"symptom": "s", "repro_steps": ["r"]},
            "lesson": {
                "mistake": "m",
                "rule": rule,
                "scope": {"task_kinds": ["impl"]},
                "enforcement": {"mode": "warn", "applies_to": "workflow_gate"},
            },
        }
    }


def _rich_history(root: Path, repo_root: Path) -> ESAAService:
    """Log com todas as acoes relevantes ao projetor."""
    roadmap = root / ".roadmap"
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "roadmap.schema.json", roadmap / "roadmap.schema.json"
    )
    (roadmap / "RUNTIME_POLICY.yaml").write_text('review_authorization: "qa_role"\n', encoding="utf-8")
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.create_task("T-B", "impl", "depende de A", outputs=["src/b.txt"], depends_on=["T-A"])
    service.create_task("T-OLD", "spec", "sera substituida", outputs=["docs/spec/old.md"])
    service.create_task("T-NEW", "spec", "substitui", outputs=["docs/spec/new.md"], supersedes=["T-OLD"])
    service.amend_task("T-B", title="titulo alterado", description="descricao alterada")
    service.claim_task("T-A", actor="agent-impl")
    service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "a\n"}]
    )
    service.review_task("T-A", actor="agent-qa", decision="request_changes")
    service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "b\n"}]
    )
    service.review_task("T-A", actor="agent-qa", decision="approve")
    service.submit(_lesson_report("ISS-L1", "regra um"), actor="agent-impl")
    service.submit(_lesson_report("ISS-L2", "regra dois"), actor="agent-impl")
    proposed = {
        item["rule"]: item["lesson_id"] for item in service.list_lessons(status="proposed")["lessons"]
    }
    service.decide_lesson(proposed["regra um"], "approve", reason="ok")
    service.decide_lesson(proposed["regra dois"], "reject", reason="nao")
    service.report_issue(
        "T-A",
        actor="agent-qa",
        issue_id="ISS-HF",
        severity="high",
        title="defeito",
        symptom="s",
        repro_steps=["r"],
        fixes="T-A",
    )
    service.claim_task("HF-ISS-HF", actor="agent-impl")
    service.complete_task(
        "HF-ISS-HF",
        actor="agent-impl",
        checks=["unit", "regression"],
        file_updates=[{"path": "src/hotfix/fix.txt", "content": "fix\n"}],
        issue_id="ISS-HF",
        fixes="T-A",
    )
    service.review_task("HF-ISS-HF", actor="agent-qa", decision="approve")
    service.reject_output("T-B", "X", "complete", "m")
    service.claim_task("T-B", actor="agent-impl")
    return service


def _views(root: Path) -> dict[str, Any]:
    return {
        name: json.loads((root / ".roadmap" / name).read_text(encoding="utf-8"))
        for name in ("roadmap.json", "issues.json", "lessons.json")
    }


def test_rich_history_covers_the_relevant_actions(contract_bundle: Path, repo_root: Path) -> None:
    _rich_history(contract_bundle, repo_root)
    actions = {event["action"] for event in parse_event_store(contract_bundle)}

    assert {
        "run.start",
        "task.create",
        "task.amend",
        "claim",
        "complete",
        "review",
        "issue.report",
        "hotfix.create",
        "issue.resolve",
        "orchestrator.file.write",
        "orchestrator.view.mutate",
        "output.rejected",
        "verify.start",
        "verify.ok",
    } <= actions


def test_incremental_application_equals_full_replay_at_every_split(
    contract_bundle: Path, repo_root: Path
) -> None:
    _rich_history(contract_bundle, repo_root)
    events = parse_event_store(contract_bundle)
    expected = materialize(events)

    for split in range(len(events) + 1):
        state = replay_state(events[:split])
        if split:
            finalize_views(state)  # finalizar no meio nao pode alterar o estado
        apply_events(state, events[split:])
        assert finalize_views(state) == expected, split

    one_by_one = replay_state([])
    for event in events:
        apply_events(one_by_one, [event])
    assert finalize_views(one_by_one) == expected


def test_summary_matches_roadmap_view_and_views_are_independent_copies(
    contract_bundle: Path, repo_root: Path
) -> None:
    _rich_history(contract_bundle, repo_root)
    events = parse_event_store(contract_bundle)
    state = replay_state(events)
    roadmap, issues, lessons = finalize_views(state)

    assert projection_summary(state) == roadmap["meta"]["run"]
    assert [task["task_id"] for task in state_tasks(state)] == [task["task_id"] for task in roadmap["tasks"]]

    roadmap["tasks"][0]["status"] = "adulterado"
    issues["issues"][0]["status"] = "adulterado"
    lessons["lessons"][0]["rule"] = "adulterado"
    assert finalize_views(state) == materialize(events)


def test_service_writes_the_same_projections_as_a_replay_from_scratch(
    contract_bundle: Path, repo_root: Path
) -> None:
    service = _rich_history(contract_bundle, repo_root)
    written = _views(contract_bundle)
    roadmap, issues, lessons = materialize(parse_event_store(contract_bundle))

    assert written == {"roadmap.json": roadmap, "issues.json": issues, "lessons.json": lessons}
    before = {name: (contract_bundle / ".roadmap" / name).read_bytes() for name in written}
    service.project()
    assert {name: (contract_bundle / ".roadmap" / name).read_bytes() for name in written} == before
    assert service.verify()["verify_status"] == "ok"


def test_command_responses_keep_the_committed_task_snapshot(contract_bundle: Path) -> None:
    (contract_bundle / ".roadmap" / "RUNTIME_POLICY.yaml").write_text('review_authorization: "qa_role"\n')
    service = ESAAService(contract_bundle)
    service.init(force=True)
    service.create_task("T-A", "impl", "a", outputs=["src/a.txt"])
    operations = [
        lambda: service.claim_task("T-A", actor="agent-impl"),
        lambda: service.complete_task("T-A", actor="agent-impl", checks=["unit"]),
        lambda: service.review_task("T-A", actor="agent-qa", decision="request_changes"),
        lambda: service.complete_task("T-A", actor="agent-impl", checks=["unit"]),
        lambda: service.review_task("T-A", actor="agent-qa", decision="approve"),
    ]
    for operation in operations:
        result = operation()
        expected = service.task_state("T-A")["task"]
        assert result["task"] == expected
        result["task"]["outputs"]["files"].append("src/injected.txt")
        assert service.task_state("T-A")["task"] == expected


def test_task_order_and_first_wins_on_duplicate_task_id() -> None:
    def create(seq: int, task_id: str, title: str) -> dict[str, Any]:
        payload = {
            "task_id": task_id,
            "task_kind": "impl",
            "title": title,
            "depends_on": [],
            "targets": [],
            "outputs": {"files": []},
        }
        return make_event(seq, actor="orchestrator", action="task.create", payload=payload)

    events = [create(1, "T-2", "segunda"), create(2, "T-1", "primeira"), create(3, "T-2", "duplicada")]
    events.append(
        make_event(
            4,
            actor="a",
            action="claim",
            payload={"action": "claim", "task_id": "T-2", "prior_status": "todo"},
        )
    )

    tasks = materialize(events)[0]["tasks"]

    assert [(task["task_id"], task["title"], task["status"]) for task in tasks] == [
        ("T-2", "segunda", "in_progress"),
        ("T-1", "primeira", "todo"),
        ("T-2", "duplicada", "todo"),
    ]


def test_rejected_candidate_reports_the_same_error_as_full_replay(
    contract_bundle: Path, repo_root: Path
) -> None:
    _rich_history(contract_bundle, repo_root)
    events = parse_event_store(contract_bundle)
    bad = make_event(
        next_event_seq(events),
        actor="agent-impl",
        action="claim",
        payload={"action": "claim", "task_id": "T-A", "prior_status": "todo"},
    )

    with pytest.raises(ESAAError) as full:
        materialize(events + [bad])
    with pytest.raises(ESAAError) as incremental:
        apply_events(replay_state(events), [bad])

    assert (incremental.value.code, incremental.value.message) == (full.value.code, full.value.message)


def test_validated_digest_fast_path_returns_equal_fresh_events(
    contract_bundle: Path, repo_root: Path
) -> None:
    _rich_history(contract_bundle, repo_root)
    store._VALIDATED_STORE_DIGESTS.clear()
    first = parse_event_store(contract_bundle)  # validacao completa
    second = parse_event_store(contract_bundle)  # mesmo conteudo: caminho rapido

    assert second == first
    assert all(a is not b for a, b in zip(first, second, strict=True))
    second[0]["payload"]["adulterado"] = True
    assert "adulterado" not in parse_event_store(contract_bundle)[0]["payload"]


def test_changed_store_content_is_fully_validated_again(contract_bundle: Path, repo_root: Path) -> None:
    _rich_history(contract_bundle, repo_root)
    path = contract_bundle / ".roadmap" / "activity.jsonl"
    original = path.read_text(encoding="utf-8")
    parse_event_store(contract_bundle)

    lines = original.splitlines()
    path.write_text("\n".join(lines[:5] + lines[6:]) + "\n", encoding="utf-8")  # remove um evento do meio
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(contract_bundle)
    assert exc.value.code == "EVENT_SEQ_NON_MONOTONIC"

    path.write_text(original + '{"schema_version":"0.4.1","event_id":"EV-0', encoding="utf-8")
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(contract_bundle)
    assert exc.value.code == "JSONL_INVALID"

    path.write_text(original, encoding="utf-8")
    assert len(parse_event_store(contract_bundle)) == len(lines)


@pytest.mark.parametrize("line", ['{}, {}', '{"event_seq":1', '[]', 'null'])
def test_bulk_decode_preserves_line_validation(contract_bundle: Path, line: str) -> None:
    path = contract_bundle / ".roadmap" / "activity.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(contract_bundle)
    assert exc.value.code == "JSONL_INVALID"


def test_digest_cache_rechecks_external_anchor(tmp_path: Path, repo_root: Path) -> None:
    from test_actor_registration import _activated

    _activated(tmp_path, repo_root)
    parse_event_store(tmp_path)
    parse_event_store(tmp_path)  # warm the unchanged-content path
    (tmp_path / ".roadmap" / "governance-anchor.json").unlink()
    with pytest.raises(CorruptedStoreError) as exc:
        parse_event_store(tmp_path)
    assert exc.value.code == "ANCHOR_MISSING"


def test_identity_fast_path_only_for_purely_legacy_history(contract_bundle: Path, repo_root: Path) -> None:
    _rich_history(contract_bundle, repo_root)
    events = parse_event_store(contract_bundle)
    assert _has_identity_material(events) is False
    validate_identity_history(contract_bundle, events)

    def variant(**changes: Any) -> list[dict[str, Any]]:
        event = dict(events[-1])
        event["payload"] = dict(event["payload"])
        for key, value in changes.items():
            if key.startswith("payload_"):
                event["payload"][key[len("payload_") :]] = value
            else:
                event[key] = value
        return events[:-1] + [event]

    for history in (
        variant(payload__authorization={"payload": {}, "signature_hex": "00"}),
        variant(payload_authorization={}),
        variant(payload_identity_epoch="esaa.identity.v9"),
        variant(action="actor.register"),
        variant(authorization={}),
        variant(payload="nao e objeto"),
    ):
        assert _has_identity_material(history) is True
        with pytest.raises(CorruptedStoreError):
            validate_identity_history(contract_bundle, history)

    # Campo legado `data`: nao e erro por si so, mas segue pelo caminho completo.
    legacy_data = variant(data={})
    assert _has_identity_material(legacy_data) is True
    validate_identity_history(contract_bundle, legacy_data)


def _synthetic_events(count: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        make_event(
            1, actor="orchestrator", action="run.start", payload={"run_id": "R", "status": "initialized"}
        )
    ]
    index = 0
    while len(events) < count:
        index += 1
        task_id = f"T-{index:06d}"
        seq = len(events)
        create = {
            "task_id": task_id,
            "task_kind": "impl",
            "title": task_id,
            "depends_on": [],
            "targets": [],
            "outputs": {"files": [f"src/{task_id}.txt"]},
        }
        events.append(make_event(seq + 1, actor="orchestrator", action="task.create", payload=create))
        events.append(
            make_event(
                seq + 2,
                actor="agent-impl",
                action="claim",
                payload={"action": "claim", "task_id": task_id, "prior_status": "todo"},
            )
        )
        events.append(
            make_event(
                seq + 3,
                actor="agent-impl",
                action="complete",
                payload={
                    "action": "complete",
                    "task_id": task_id,
                    "prior_status": "in_progress",
                    "verification": {"checks": ["c"]},
                },
            )
        )
        events.append(
            make_event(
                seq + 4,
                actor="agent-qa",
                action="review",
                payload={
                    "action": "review",
                    "task_id": task_id,
                    "prior_status": "review",
                    "decision": "approve",
                    "tasks": [task_id],
                    "_reviewer_role": "qa",
                },
            )
        )
    return events


def test_scale_guard_replay_is_not_quadratic() -> None:
    """Guarda contra regressao quadratica, nao benchmark.

    24.000 eventos (6.000 tarefas). Com a busca linear anterior este replay levava
    dezenas de segundos; com o indice leva uma fracao de segundo. O limite de 10 s e
    folgado de proposito para nao oscilar em CI lento.
    """
    events = _synthetic_events(24_000)

    started = time.perf_counter()
    roadmap, _, _ = materialize(events)
    elapsed = time.perf_counter() - started

    assert roadmap["indexes"]["by_status"] == {"done": 6000}
    assert elapsed < 10.0, f"replay de {len(events)} eventos levou {elapsed:.1f}s"


def test_scale_guard_claim_on_a_long_history(contract_bundle: Path) -> None:
    """Guarda de escala para um comando de escrita completo (parse, replay, append, projecoes)."""
    service = ESAAService(contract_bundle)
    service.init(force=True)
    history = parse_event_store(contract_bundle)
    extra = _synthetic_events(12_000)[1:]
    for offset, event in enumerate(extra):
        seq = len(history) + offset + 1
        event["event_seq"], event["event_id"] = seq, f"EV-{seq:08d}"
    append_events(contract_bundle, extra)
    service.project()
    service.create_task("T-NEXT", "impl", "proxima", outputs=["src/next.txt"])

    started = time.perf_counter()
    result = service.claim_task("T-NEXT", actor="agent-impl")
    elapsed = time.perf_counter() - started

    assert result["status"] == "accepted"
    assert service.verify()["verify_status"] == "ok"
    assert elapsed < 15.0, f"claim sobre {len(history) + len(extra)} eventos levou {elapsed:.1f}s"


@pytest.mark.skipif(
    os.environ.get("ESAA_RUN_PERFORMANCE_BENCHMARK") != "1",
    reason="wall-clock acceptance benchmark; set ESAA_RUN_PERFORMANCE_BENCHMARK=1 on the reference host",
)
def test_acceptance_cli_claim_and_verify_50k(contract_bundle: Path, repo_root: Path) -> None:
    """Audit workload: 8,333 tasks, six events per task, fresh CLI processes, <3s each."""
    events = [make_event(1, actor="orchestrator", action="run.start", payload={"run_id": "R"})]
    for index in range(8333):
        task_id = f"T-{index:06d}"
        cycle = _synthetic_events(5)[1:]
        for event in cycle:
            event["payload"]["task_id"] = task_id
        cycle[0]["payload"].update(title=task_id, description="d" * 200)
        cycle[0]["payload"]["outputs"]["files"] = [f"src/{task_id}.txt"]
        cycle[-1]["payload"]["tasks"] = [task_id]
        cycle[3:3] = [
            make_event(1, actor="orchestrator", action="verify.start", payload={"strict": True}),
            make_event(1, actor="orchestrator", action="verify.ok", payload={"projection_hash_sha256": "x"}),
        ]
        events.extend(cycle)
    events.append(make_event(50_000, actor="orchestrator", action="task.create", payload={
        "task_id": "T-NEXT", "task_kind": "impl", "title": "next",
        "outputs": {"files": ["src/next.txt"]},
    }))
    for seq, event in enumerate(events, 1):
        event["event_seq"], event["event_id"] = seq, f"EV-{seq:08d}"
    assert len(events) == 50_000
    append_events(contract_bundle, events)
    ESAAService(contract_bundle).project()
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    for command in (["verify"], ["claim", "T-NEXT", "--actor", "agent-impl"]):
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-B", "-m", "esaa", "--root", str(contract_bundle), "--runner", env.get("ESAA_RUNNER_ID", "unattended"), *command],
            env=env, capture_output=True, text=True, check=True,
        )
        elapsed = time.perf_counter() - started
        output = json.loads(result.stdout)
        assert output["verify_status"] == "ok"
        if command[0] == "claim":
            assert output["task"]["status"] == "in_progress"
        print(f"{command[0]} 50000 events: {elapsed:.3f}s")
        assert elapsed < 3.0, f"{command[0]} took {elapsed:.3f}s (acceptance: <3s)"
