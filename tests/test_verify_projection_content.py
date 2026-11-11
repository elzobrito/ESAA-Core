"""AUD-O0-060 (GOV-05) - verify compara o conteudo das projecoes com o replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from esaa import cli
from esaa.projection_check import REBUILD_HINT, compare_projections, read_projection
from esaa.service import ESAAService


def _initialized(root: Path) -> ESAAService:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")
    return service


def _full_cycle(root: Path) -> ESAAService:
    service = _initialized(root)
    service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": "src/a.txt", "content": "a\n"}]
    )
    service.review_task("T-A", actor="agent-impl", decision="approve")
    service.report_issue(
        "T-A", actor="agent-impl", issue_id="ISS-1", severity="low", title="t", symptom="s", repro_steps=["r"]
    )
    return service


def _path(root: Path, name: str) -> Path:
    return root / ".roadmap" / name


def _edit(root: Path, name: str, mutate: Any) -> None:
    path = _path(root, name)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tamper_roadmap(data: dict[str, Any]) -> None:
    data["tasks"][0]["status"] = "done"  # mantem meta.run.projection_hash_sha256 intacto


def _tamper_lessons(data: dict[str, Any]) -> None:
    data["lessons"][0]["rule"] = "REGRA ADULTERADA NO ARQUIVO"


def _empty_issues(data: dict[str, Any]) -> None:
    data["issues"] = []


def test_fresh_workspace_is_ok(contract_bundle: Path) -> None:
    service = ESAAService(contract_bundle)
    service.init(force=True)

    result = service.verify()

    assert result["verify_status"] == "ok"
    assert "divergent" not in result


def test_full_cycle_workspace_is_ok(contract_bundle: Path) -> None:
    service = _full_cycle(contract_bundle)

    assert service.task_state("T-A")["task"]["status"] == "done"
    assert service.verify()["verify_status"] == "ok"


def test_tampered_roadmap_with_intact_hash_field_is_mismatch(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)
    before = service.verify()

    _edit(contract_bundle, "roadmap.json", _tamper_roadmap)
    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["roadmap.json"]
    assert result["hint"] == REBUILD_HINT
    # o campo de hash declarado continua batendo: so a comparacao de conteudo detecta
    assert result["stored_projection_hash_sha256"] == before["projection_hash_sha256"]
    assert result["stored_last_event_seq"] == before["last_event_seq"]
    assert result["project_profile_mismatch"] is False
    assert service.task_state("T-A")["task"]["status"] == "in_progress"


def test_tampered_lessons_is_mismatch(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)

    _edit(contract_bundle, "lessons.json", _tamper_lessons)
    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["lessons.json"]


def test_emptied_issues_is_mismatch(contract_bundle: Path) -> None:
    service = _full_cycle(contract_bundle)

    _edit(contract_bundle, "issues.json", _empty_issues)
    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["issues.json"]


def test_two_tampered_projections_are_both_listed(contract_bundle: Path) -> None:
    service = _full_cycle(contract_bundle)

    _edit(contract_bundle, "issues.json", _empty_issues)
    _edit(contract_bundle, "lessons.json", _tamper_lessons)
    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["issues.json", "lessons.json"]


def test_reformatted_but_equal_projection_is_ok(contract_bundle: Path) -> None:
    """A comparacao e de conteudo JSON, nao de bytes: reformatar o arquivo nao e divergencia."""
    service = _initialized(contract_bundle)
    path = _path(contract_bundle, "roadmap.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    assert service.verify()["verify_status"] == "ok"


def test_truncated_roadmap_is_mismatch_without_exception(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)
    path = _path(contract_bundle, "roadmap.json")
    path.write_text(path.read_text(encoding="utf-8")[:100], encoding="utf-8")

    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["roadmap.json"]
    assert result["unreadable"] == {"roadmap.json": "unreadable"}
    assert result["stored_projection_hash_sha256"] is None


def test_missing_issues_file_is_mismatch(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)
    _path(contract_bundle, "issues.json").unlink()

    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["issues.json"]
    assert result["unreadable"] == {"issues.json": "missing"}


def test_missing_roadmap_keeps_legacy_reason(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)
    _path(contract_bundle, "roadmap.json").unlink()

    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["reason"] == "roadmap_missing"


def test_non_object_projection_is_mismatch(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)
    _path(contract_bundle, "roadmap.json").write_text("[]\n", encoding="utf-8")

    result = service.verify()

    assert result["verify_status"] == "mismatch"
    assert result["divergent"] == ["roadmap.json"]


def test_project_restores_ok_after_tampering(contract_bundle: Path) -> None:
    service = _full_cycle(contract_bundle)
    _edit(contract_bundle, "roadmap.json", lambda data: data["tasks"][0].update(title="adulterado"))
    _path(contract_bundle, "issues.json").write_text("{", encoding="utf-8")
    _path(contract_bundle, "lessons.json").unlink()
    assert service.verify()["divergent"] == ["roadmap.json", "issues.json", "lessons.json"]

    service.project()

    assert service.verify()["verify_status"] == "ok"


def test_empty_store_ignores_only_clock_based_updated_at(contract_bundle: Path) -> None:
    """Sem eventos, meta.updated_at vem do relogio; qualquer outra diferenca ainda e detectada."""
    service = ESAAService(contract_bundle)
    _path(contract_bundle, "activity.jsonl").write_text("", encoding="utf-8")
    service.project()
    _edit(
        contract_bundle, "roadmap.json", lambda data: data["meta"].update(updated_at="2000-01-01T00:00:00Z")
    )
    assert service.verify()["verify_status"] == "ok"

    _edit(contract_bundle, "roadmap.json", lambda data: data["project"].update(name="adulterado"))

    assert service.verify()["divergent"] == ["roadmap.json"]


def test_updated_at_is_compared_when_events_exist(contract_bundle: Path) -> None:
    service = _initialized(contract_bundle)

    _edit(contract_bundle, "issues.json", lambda data: data["meta"].update(updated_at="2000-01-01T00:00:00Z"))

    assert service.verify()["divergent"] == ["issues.json"]


def test_cli_exit_code_is_2_on_content_mismatch(
    contract_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _initialized(contract_bundle)
    assert cli.main(["--root", str(contract_bundle), "verify"]) == 0
    _edit(contract_bundle, "lessons.json", _tamper_lessons)
    capsys.readouterr()

    rc = cli.main(["--root", str(contract_bundle), "verify"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verify_status"] == "mismatch"
    assert payload["divergent"] == ["lessons.json"]


def test_helpers_report_problems(tmp_path: Path) -> None:
    assert read_projection(tmp_path / "nope.json") == (None, "missing")
    (tmp_path / "bad.json").write_bytes(b"\xff\xfe{")
    assert read_projection(tmp_path / "bad.json") == (None, "unreadable")

    check = compare_projections(tmp_path, {"roadmap.json": {}, "issues.json": {}, "lessons.json": {}})

    assert check["divergent"] == ["roadmap.json", "issues.json", "lessons.json"]
    assert set(check["problems"].values()) == {"missing"}
    assert check["stored_roadmap"] is None
