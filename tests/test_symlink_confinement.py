"""AUD-O0-050 (SEC-03/GOV-08) - efeitos confinados ao root e destino validado antes do append."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from rejection_assertions import assert_only_rejection_events

from esaa import cli
from esaa.errors import ESAAError
from esaa.file_effects import assert_confined_destination, recover_file_effects
from esaa.service import ESAAService
from esaa.store import parse_event_store

pytestmark = pytest.mark.skipif(os.name != "posix", reason="symlink semantics require POSIX")


def _service(root: Path) -> ESAAService:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")
    return service


def _complete(service: ESAAService, path: str, **kwargs: Any) -> dict[str, Any]:
    return service.complete_task(
        "T-A", actor="agent-impl", checks=["unit"], file_updates=[{"path": path, "content": "x\n"}], **kwargs
    )


def _assert_rejected_without_trace(service: ESAAService, root: Path, path: str, **kwargs: Any) -> ESAAError:
    before_events = len(parse_event_store(root))
    artifacts = root / ".roadmap" / "artifacts" / "file-effects"
    before_artifacts = sorted(p.name for p in artifacts.glob("*")) if artifacts.exists() else []

    with pytest.raises(ESAAError) as exc:
        _complete(service, path, **kwargs)

    assert exc.value.code == "BOUNDARY_VIOLATION"
    if kwargs.get("dry_run"):
        assert len(parse_event_store(root)) == before_events
    else:
        assert_only_rejection_events(root, before_events, exc.value.code)
    assert service.task_state("T-A")["task"]["status"] == "in_progress"
    assert (sorted(p.name for p in artifacts.glob("*")) if artifacts.exists() else []) == before_artifacts
    staging = root / ".roadmap" / "staging"
    assert not staging.exists() or list(staging.glob("stage-*.tmp")) == []
    assert service.verify()["verify_status"] == "ok"
    return exc.value


@pytest.fixture
def outside(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("outside")


def test_ancestor_symlink_to_outside_is_rejected(contract_bundle: Path, outside: Path) -> None:
    service = _service(contract_bundle)
    (contract_bundle / "src" / "link").symlink_to(outside, target_is_directory=True)

    error = _assert_rejected_without_trace(service, contract_bundle, "src/link/sub/pwn.txt")

    assert "outside the authorized root" in error.message
    assert list(outside.iterdir()) == []


def test_immediate_parent_symlink_to_outside_is_rejected(contract_bundle: Path, outside: Path) -> None:
    service = _service(contract_bundle)
    (contract_bundle / "src" / "link").symlink_to(outside, target_is_directory=True)

    _assert_rejected_without_trace(service, contract_bundle, "src/link/pwn2.txt")

    assert list(outside.iterdir()) == []


def test_destination_symlink_is_rejected_even_inside_root(contract_bundle: Path, outside: Path) -> None:
    service = _service(contract_bundle)
    inner = contract_bundle / "src" / "real.txt"
    inner.write_text("original\n", encoding="utf-8")
    (contract_bundle / "src" / "alias.txt").symlink_to(inner)
    victim = outside / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    (contract_bundle / "src" / "escape.txt").symlink_to(victim)

    _assert_rejected_without_trace(service, contract_bundle, "src/alias.txt")
    _assert_rejected_without_trace(service, contract_bundle, "src/escape.txt")

    assert inner.read_text(encoding="utf-8") == "original\n"
    assert victim.read_text(encoding="utf-8") == "untouched\n"


def test_destination_directory_is_rejected(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    (contract_bundle / "src" / "pkg").mkdir()

    _assert_rejected_without_trace(service, contract_bundle, "src/pkg")


def test_regular_file_as_path_component_is_rejected(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    (contract_bundle / "src" / "blocker").write_text("sou arquivo\n", encoding="utf-8")

    for path in ("src/blocker/x.txt", "src/blocker/deep/x.txt"):
        error = _assert_rejected_without_trace(service, contract_bundle, path)
        assert "not a directory" in error.message

    assert (contract_bundle / "src" / "blocker").read_text(encoding="utf-8") == "sou arquivo\n"


def test_dry_run_is_also_rejected(contract_bundle: Path, outside: Path) -> None:
    service = _service(contract_bundle)
    (contract_bundle / "src" / "link").symlink_to(outside, target_is_directory=True)

    _assert_rejected_without_trace(service, contract_bundle, "src/link/sub/pwn.txt", dry_run=True)

    assert list(outside.iterdir()) == []


def test_new_nested_directories_are_still_accepted(contract_bundle: Path) -> None:
    service = _service(contract_bundle)

    result = _complete(service, "src/a/b/c/novo.txt")

    assert result["status"] == "accepted"
    assert (contract_bundle / "src" / "a" / "b" / "c" / "novo.txt").read_text(encoding="utf-8") == "x\n"
    assert service.verify()["verify_status"] == "ok"


def test_overwriting_regular_file_is_still_accepted(contract_bundle: Path) -> None:
    service = _service(contract_bundle)
    target = contract_bundle / "src" / "a.txt"
    target.write_text("antigo\n", encoding="utf-8")

    _complete(service, "src/a.txt")

    assert target.read_text(encoding="utf-8") == "x\n"


def test_internal_ancestor_symlink_inside_root_is_accepted(contract_bundle: Path) -> None:
    """Symlink de diretorio que resolve para dentro do root continua permitido como ancestral."""
    service = _service(contract_bundle)
    (contract_bundle / "src" / "real").mkdir()
    (contract_bundle / "src" / "inner").symlink_to(contract_bundle / "src" / "real", target_is_directory=True)

    result = _complete(service, "src/inner/sub/ok.txt")

    assert result["status"] == "accepted"
    assert (contract_bundle / "src" / "real" / "sub" / "ok.txt").read_text(encoding="utf-8") == "x\n"


def test_internal_symlink_as_immediate_parent_is_rejected_before_append(contract_bundle: Path) -> None:
    """Pai imediato symlink ja falhava no commit (O_NOFOLLOW); agora falha limpo antes do append."""
    service = _service(contract_bundle)
    (contract_bundle / "src" / "real").mkdir()
    (contract_bundle / "src" / "inner").symlink_to(contract_bundle / "src" / "real", target_is_directory=True)

    error = _assert_rejected_without_trace(service, contract_bundle, "src/inner/ok.txt")

    assert "parent directory is a symlink" in error.message
    assert list((contract_bundle / "src" / "real").iterdir()) == []


def test_cli_reports_boundary_violation_without_traceback(
    contract_bundle: Path, outside: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _service(contract_bundle)
    (contract_bundle / "src" / "link").symlink_to(outside, target_is_directory=True)
    updates = contract_bundle / "fu.json"
    updates.write_text('[{"path":"src/link/pwn2.txt","content":"x"}]', encoding="utf-8")
    capsys.readouterr()

    rc = cli.main(
        [
            "--root",
            str(contract_bundle),
            "complete",
            "T-A",
            "--actor",
            "agent-impl",
            "--check",
            "unit",
            "--file-updates",
            str(updates),
        ]
    )

    err = capsys.readouterr().err
    assert rc == 1
    assert '"error_code": "BOUNDARY_VIOLATION"' in err
    assert "Traceback" not in err


def test_recover_does_not_follow_symlink_planted_after_the_fact(contract_bundle: Path, outside: Path) -> None:
    service = _service(contract_bundle)
    _complete(service, "src/dir/a.txt")
    target_dir = contract_bundle / "src" / "dir"
    (target_dir / "a.txt").unlink()
    target_dir.rmdir()
    target_dir.symlink_to(outside, target_is_directory=True)

    result = recover_file_effects(contract_bundle, parse_event_store(contract_bundle))

    assert result["files_recovered"] == 0
    assert [item["path"] for item in result["errors"]] == ["src/dir/a.txt"]
    assert list(outside.iterdir()) == []


def test_external_destination_is_confined_to_its_target_root(tmp_path: Path, outside: Path) -> None:
    target_root = tmp_path / "ext"
    target_root.mkdir()
    (target_root / "link").symlink_to(outside, target_is_directory=True)

    ok = assert_confined_destination(
        tmp_path, "runtime://x/a.txt", str(target_root / "pkg" / "a.txt"), str(target_root)
    )
    assert ok == target_root / "pkg" / "a.txt"
    with pytest.raises(ESAAError) as exc:
        assert_confined_destination(
            tmp_path, "runtime://x/b.txt", str(target_root / "link" / "sub" / "b.txt"), str(target_root)
        )
    assert exc.value.code == "BOUNDARY_VIOLATION"
