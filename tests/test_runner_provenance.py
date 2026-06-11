"""G08 (PROV-01/PROV-02): proveniencia de runner em eventos do ESAA."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from esaa.errors import CorruptedStoreError, ESAAError
from esaa.projector import materialize
from esaa.provenance import (
    DEFAULT_RUNNER_ID,
    ENV_COMMAND_SURFACE,
    ENV_ON_BEHALF_OF,
    ENV_RUNNER_ID,
    ENV_RUNNER_KIND,
    resolve_runner,
    validate_runner_block,
)
from esaa.runtime_policy import known_runners, validate_runner_id
from esaa.service import make_event
from esaa.store import load_agent_contract, load_agent_result_schema, parse_event_store
from esaa.validator import validate_agent_output


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENV_RUNNER_ID, ENV_RUNNER_KIND, ENV_COMMAND_SURFACE, ENV_ON_BEHALF_OF):
        monkeypatch.delenv(name, raising=False)


# --- PROV-01: resolucao e carimbo -------------------------------------------


def test_default_runner_is_unattended(clean_env: None) -> None:
    block = resolve_runner()
    assert block["runner_id"] == DEFAULT_RUNNER_ID
    assert block["command_surface"] == "cli"
    assert block["runner_kind"] is None
    assert block["on_behalf_of"] is None


def test_env_overrides_are_respected(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_RUNNER_ID, "claude-cowork")
    monkeypatch.setenv(ENV_RUNNER_KIND, "llm-agent")
    monkeypatch.setenv(ENV_ON_BEHALF_OF, "user@example.com")
    block = resolve_runner()
    assert block == {
        "runner_id": "claude-cowork",
        "runner_kind": "llm-agent",
        "command_surface": "cli",
        "on_behalf_of": "user@example.com",
    }


def test_make_event_stamps_runner(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_RUNNER_ID, "claude-cowork")
    event = make_event(1, actor="agent-impl", action="claim", payload={"task_id": "T-1"})
    assert event["runner"]["runner_id"] == "claude-cowork"
    # actor (papel) e runner (principal) sao eixos independentes
    assert event["actor"] == "agent-impl"


@pytest.mark.parametrize("bad", [None, "str", 1, {}, {"runner_id": ""}, {"runner_id": 3}])
def test_validate_runner_block_fail_closed(bad: object) -> None:
    with pytest.raises(ESAAError):
        validate_runner_block(bad)


# --- PROV-01: compatibilidade de store e replay ------------------------------


def _base_event(seq: int, runner: dict | None = None) -> dict:
    event = {
        "schema_version": "0.4.1",
        "event_id": f"EV-{seq:08d}",
        "event_seq": seq,
        "ts": "2026-06-09T12:00:00Z",
        "actor": "orchestrator",
        "action": "task.create",
        "payload": {
            "task_id": f"T-{seq:03d}",
            "task_kind": "spec",
            "title": "t",
            "description": "d",
            "status": "todo",
            "depends_on": [],
            "targets": ["X-1"],
            "outputs": {"files": ["docs/x.md"]},
            "immutability": {"done_is_immutable": True},
        },
    }
    if runner is not None:
        event["runner"] = runner
    return event


def _write_store(root: Path, events: list[dict]) -> None:
    store = root / ".roadmap" / "activity.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8"
    )


def test_legacy_events_without_runner_parse(tmp_path: Path) -> None:
    _write_store(tmp_path, [_base_event(1)])
    events = parse_event_store(tmp_path)
    assert len(events) == 1
    assert "runner" not in events[0]


def test_runner_is_forensic_not_state(tmp_path: Path) -> None:
    """Golden replay: projecao identica com e sem bloco runner."""
    runner = {"runner_id": "claude-cowork", "runner_kind": "llm-agent"}
    legacy, stamped = [_base_event(1)], [_base_event(1, runner=runner)]
    r_legacy, i_legacy, l_legacy = materialize(legacy)
    r_stamped, i_stamped, l_stamped = materialize(stamped)
    assert (
        r_legacy["meta"]["run"]["projection_hash_sha256"]
        == r_stamped["meta"]["run"]["projection_hash_sha256"]
    )
    assert r_legacy["tasks"] == r_stamped["tasks"]
    assert (i_legacy, l_legacy) == (i_stamped, l_stamped)


def test_invalid_runner_block_in_store_is_corruption(tmp_path: Path) -> None:
    _write_store(tmp_path, [_base_event(1, runner={"runner_id": ""})])
    with pytest.raises(CorruptedStoreError):
        parse_event_store(tmp_path)


# --- PROV-02: registro no swarm e modo strict --------------------------------


def _write_swarm(root: Path, runners: dict) -> None:
    import yaml

    path = root / ".roadmap" / "agents_swarm.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"agents": {}, "runners": runners}), encoding="utf-8")


def test_known_runners_reads_swarm_section(tmp_path: Path) -> None:
    _write_swarm(tmp_path, {"alpha": {"kind": "human"}, "beta": {}})
    assert known_runners(tmp_path) == {"alpha", "beta"}


def test_strict_mode_rejects_unregistered_runner(tmp_path: Path) -> None:
    _write_swarm(tmp_path, {"alpha": {}})
    validate_runner_id("alpha", root=tmp_path, policy={"runner_validation": "strict"})
    with pytest.raises(ESAAError) as exc:
        validate_runner_id("ghost", root=tmp_path, policy={"runner_validation": "strict"})
    assert exc.value.code == "RUNNER_UNKNOWN"


def test_permissive_mode_accepts_anything(tmp_path: Path) -> None:
    validate_runner_id("ghost", root=tmp_path, policy={})
    validate_runner_id("ghost", root=tmp_path, policy={"runner_validation": "permissive"})


# --- Defesa em profundidade: agente nao envia runner --------------------------


def test_agent_envelope_with_runner_is_rejected(contract_bundle: Path) -> None:
    schema = load_agent_result_schema(contract_bundle)
    contract = load_agent_contract(contract_bundle)
    task = {"task_id": "T-001", "task_kind": "spec", "status": "todo"}
    output = {
        "activity_event": {
            "action": "claim",
            "task_id": "T-001",
            "prior_status": "todo",
            "runner": {"runner_id": "forjado"},
        }
    }
    with pytest.raises(ESAAError):
        validate_agent_output(output, schema, contract, task)


def test_runner_codes_registered_in_vocabulary() -> None:
    from esaa import reject_codes

    assert "RUNNER_INVALID" in reject_codes.ALL_CODES
    assert "RUNNER_UNKNOWN" in reject_codes.ALL_CODES
