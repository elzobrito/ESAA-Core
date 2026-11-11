"""AUD-O1-030 (GOV-07) - visibilidade da cadeia de hash e aviso de ts regressivo.

A cadeia sem ancora continua sendo o padrao (decisao de arquitetura); estes
testes cobrem apenas a visibilidade (`chain_status`), a ancora opt-in no init e
o aviso informativo de timestamp regressivo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from esaa import cli
from esaa.service import ESAAService
from esaa.store import init_hash_chain
from esaa.verify_annotations import TS_REGRESSION_CODE, chain_status, ts_regression_warning


def _store(root: Path) -> Path:
    return root / ".roadmap" / "activity.jsonl"


def _run(root: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    rc = cli.main(["--root", str(root), *argv])
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else {})


def _rewrite(root: Path, mutate: Any) -> None:
    events = [
        json.loads(line) for line in _store(root).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    mutate(events)
    text = "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events)
    _store(root).write_text(text, encoding="utf-8")


def test_default_workspace_reports_unanchored_and_stays_ok(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])

    result = service.verify()

    assert result["verify_status"] == "ok"
    assert result["chain_status"] == "unanchored"
    assert "warnings" not in result


def test_init_without_flag_does_not_anchor(contract_bundle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, result = _run(contract_bundle, capsys, "init", "--force")

    assert rc == 0 and "chain" not in result
    assert '"chain.anchor"' not in _store(contract_bundle).read_text(encoding="utf-8")


def test_init_with_chain_anchors_and_tamper_is_detected(
    contract_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, result = _run(contract_bundle, capsys, "init", "--force", "--with-chain")
    assert rc == 0
    assert result["chain"]["status"] == "anchored"

    service = ESAAService(contract_bundle)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    verified = service.verify()
    assert (verified["verify_status"], verified["chain_status"]) == ("ok", "ok")

    def tamper(events: list[dict[str, Any]]) -> None:
        events[0]["ts"] = "2001-01-01T00:00:00Z"

    _rewrite(contract_bundle, tamper)
    rc_verify, corrupted = _run(contract_bundle, capsys, "verify")

    assert rc_verify == 2
    assert corrupted["verify_status"] == "corrupted"
    assert corrupted["error_code"] == "CHAIN_BROKEN"


def test_chain_status_follows_later_anchor(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)
    assert service.verify()["chain_status"] == "unanchored"

    init_hash_chain(contract_bundle)

    assert service.verify()["chain_status"] == "ok"


def test_mismatch_response_also_carries_chain_status(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    roadmap_path = contract_bundle / ".roadmap" / "roadmap.json"
    data = json.loads(roadmap_path.read_text(encoding="utf-8"))
    data["tasks"][0]["status"] = "done"
    roadmap_path.write_text(json.dumps(data), encoding="utf-8")

    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["chain_status"] == "unanchored"


def test_ts_regression_is_a_warning_not_a_failure(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])

    def regress(events: list[dict[str, Any]]) -> None:
        events[-1]["ts"] = "1999-01-01T00:00:00Z"

    _rewrite(contract_bundle, regress)
    service.project()

    result = service.verify()

    assert result["verify_status"] == "ok"
    warnings = [item for item in result["warnings"] if item["code"] == TS_REGRESSION_CODE]
    assert len(warnings) == 1
    assert warnings[0]["count"] == 1
    assert warnings[0]["first_event_seq"] == len(
        _store(contract_bundle).read_text(encoding="utf-8").splitlines()
    )


def test_ts_helpers_edge_cases() -> None:
    assert chain_status([]) == "unanchored"
    assert ts_regression_warning([]) is None
    monotonic = [{"event_seq": i, "ts": f"2026-01-01T00:00:0{i}Z"} for i in range(1, 4)]
    assert ts_regression_warning(monotonic) is None
    equal = [{"event_seq": 1, "ts": "2026-01-01T00:00:00Z"}, {"event_seq": 2, "ts": "2026-01-01T00:00:00Z"}]
    assert ts_regression_warning(equal) is None
    # ts ausente, invalido ou sem fuso nao derruba nem gera aviso falso.
    odd = [
        {"event_seq": 1, "ts": "2026-01-01T00:00:05Z"},
        {"event_seq": 2},
        {"event_seq": 3, "ts": "nao-e-data"},
        {"event_seq": 4, "ts": "2026-01-01T00:00:01"},
        {"event_seq": 5, "ts": "2026-01-01T00:00:06Z"},
    ]
    assert ts_regression_warning(odd) is None
    # um evento atrasado conta uma vez; o seguinte e comparado com o maior ts ja visto.
    late = [
        {"event_seq": 1, "ts": "2026-01-01T00:00:05Z"},
        {"event_seq": 2, "ts": "2026-01-01T00:00:01Z"},
        {"event_seq": 3, "ts": "2026-01-01T00:00:06Z"},
    ]
    warning = ts_regression_warning(late)
    assert warning is not None and (warning["count"], warning["first_event_seq"]) == (1, 2)
