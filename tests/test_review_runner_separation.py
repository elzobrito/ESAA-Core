"""AUD-O0-020 (GOV-01) - separacao opcional entre runner executor e runner revisor."""

from __future__ import annotations

from pathlib import Path

import pytest

from esaa.errors import ESAAError
from esaa.provenance import ENV_RUNNER_ID
from esaa.runtime_policy import assert_review_runner_separation, review_runner_separation_mode
from esaa.service import ESAAService


def _policy(root: Path, extra: str = "") -> None:
    (root / ".roadmap" / "RUNTIME_POLICY.yaml").write_text(
        'review_authorization: "qa_role"\n' + extra, encoding="utf-8"
    )


def _to_review(root: Path, monkeypatch: pytest.MonkeyPatch, runner: str | None = "runner-a") -> ESAAService:
    if runner is None:
        monkeypatch.delenv(ENV_RUNNER_ID, raising=False)
    else:
        monkeypatch.setenv(ENV_RUNNER_ID, runner)
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")
    service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "a\n"}]
    )
    return service


def _status(service: ESAAService) -> str:
    return service.task_state("T-A")["task"]["status"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "off"), ("off", "off"), ("enforce", "enforce"), ("ENFORCE", "enforce"), ("bogus", "off")],
)
def test_mode_parsing_defaults_to_off(value: str | None, expected: str) -> None:
    policy = {} if value is None else {"review_runner_separation": value}
    assert review_runner_separation_mode(policy) == expected


def test_default_policy_keeps_same_runner_review(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _policy(contract_bundle)
    service = _to_review(contract_bundle, monkeypatch)

    service.review_task("T-A", actor="agent-qa", decision="approve")

    assert _status(service) == "done"


def test_enforce_rejects_same_runner_with_different_actor(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _policy(contract_bundle, 'review_runner_separation: "enforce"\n')
    service = _to_review(contract_bundle, monkeypatch)

    with pytest.raises(ESAAError) as exc:
        service.review_task("T-A", actor="agent-qa", decision="approve")

    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"
    assert "runner-a" in exc.value.message
    assert _status(service) == "review"


def test_enforce_also_blocks_dry_run_and_request_changes(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _policy(contract_bundle, 'review_runner_separation: "enforce"\n')
    service = _to_review(contract_bundle, monkeypatch)

    for kwargs in ({"decision": "approve", "dry_run": True}, {"decision": "request_changes"}):
        with pytest.raises(ESAAError) as exc:
            service.review_task("T-A", actor="agent-qa", **kwargs)
        assert exc.value.code == "SELF_REVIEW_FORBIDDEN"


def test_enforce_accepts_distinct_runner(contract_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _policy(contract_bundle, 'review_runner_separation: "enforce"\n')
    service = _to_review(contract_bundle, monkeypatch)
    monkeypatch.setenv(ENV_RUNNER_ID, "runner-b")

    service.review_task("T-A", actor="agent-qa", decision="approve")

    assert _status(service) == "done"
    assert service.verify()["verify_status"] == "ok"


def test_enforce_treats_default_unattended_runner_as_same(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitir --runner nao contorna a regra: o default 'unattended' tambem e comparado."""
    _policy(contract_bundle, 'review_runner_separation: "enforce"\n')
    service = _to_review(contract_bundle, monkeypatch, runner=None)

    with pytest.raises(ESAAError) as exc:
        service.review_task("T-A", actor="agent-qa", decision="approve")

    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"


def test_enforce_uses_latest_cycle_after_request_changes(
    contract_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _policy(contract_bundle, 'review_runner_separation: "enforce"\n')
    service = _to_review(contract_bundle, monkeypatch)
    monkeypatch.setenv(ENV_RUNNER_ID, "runner-b")
    service.review_task("T-A", actor="agent-qa", decision="request_changes")
    # runner-b assume a correcao; agora e ele quem nao pode revisar.
    service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "b\n"}]
    )

    with pytest.raises(ESAAError) as exc:
        service.review_task("T-A", actor="agent-qa", decision="approve")
    assert exc.value.code == "SELF_REVIEW_FORBIDDEN"

    # runner-a fez o claim vigente: tambem continua impedido.
    monkeypatch.setenv(ENV_RUNNER_ID, "runner-a")
    with pytest.raises(ESAAError):
        service.review_task("T-A", actor="agent-qa", decision="approve")

    monkeypatch.setenv(ENV_RUNNER_ID, "runner-c")
    service.review_task("T-A", actor="agent-qa", decision="approve")
    assert _status(service) == "done"


def test_historical_events_without_runner_do_not_block() -> None:
    events = [
        {"action": "claim", "payload": {"task_id": "T-A"}},
        {"action": "complete", "payload": {"task_id": "T-A"}, "runner": None},
        {"action": "complete", "payload": {"task_id": "T-OTHER"}, "runner": {"runner_id": "runner-a"}},
    ]

    assert_review_runner_separation(events, "T-A", "runner-a")


def test_enforce_is_ignored_in_owner_mode(contract_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Modo owner e autoaprovacao por desenho; a separacao so vale em qa_role."""
    (contract_bundle / ".roadmap" / "RUNTIME_POLICY.yaml").write_text(
        'review_authorization: "owner"\nreview_runner_separation: "enforce"\n', encoding="utf-8"
    )
    service = _to_review(contract_bundle, monkeypatch)

    service.review_task("T-A", actor="agent-impl", decision="approve")

    assert _status(service) == "done"
