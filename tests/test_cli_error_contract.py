"""AUD-O1-040: expected CLI errors are JSON; missing-store reads never create files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.reject_codes import ALL_CODES, OPERATIONAL_CODES, WORKSPACE_INVALID
from esaa.service import ESAAService
from esaa.store import parse_event_store, verify_hash_chain


def _cli(
    root: Path,
    repo: Path,
    *args: str,
    input_text: str | None = None,
    debug: str = "0",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(repo / "src"),
        "ESAA_DEBUG": debug,
        "PYTHONDONTWRITEBYTECODE": "1",
        **(env_extra or {}),
    }
    return subprocess.run(
        [sys.executable, "-B", "-m", "esaa", "--root", str(root), "--runner", "codex", *args],
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _error(result: subprocess.CompletedProcess[str], code: str) -> dict[str, str]:
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1, result.stderr
    assert "Traceback" not in result.stderr
    data = json.loads(result.stderr)
    assert set(data) == {"error_code", "error_message"}
    assert data["error_code"] == code
    assert len(data["error_message"]) <= 200
    return data


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _ready(root: Path) -> None:
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "a", outputs=["src/a.txt"])
    service.claim_task("T-A", actor="agent-impl")


@pytest.mark.parametrize(
    "command",
    [
        ["eligible"],
        ["verify"],
        ["state", "T-A"],
        ["dispatch-context", "T-A"],
        ["metrics"],
        ["task", "list"],
        ["activity", "list"],
        ["replay", "--no-write"],
        ["verify", "--chain"],
    ],
)
@pytest.mark.parametrize("layout", ["empty", "absent", "roadmap-only"])
def test_missing_store_read_is_json_and_entirely_read_only(
    tmp_path: Path,
    repo_root: Path,
    command: list[str],
    layout: str,
) -> None:
    root = tmp_path / "workspace"
    if layout != "absent":
        root.mkdir()
    if layout == "roadmap-only":
        (root / ".roadmap").mkdir()
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    _error(_cli(root, repo_root, *command), "EVENT_STORE_MISSING")
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("query", ["parse", "verify", "eligible", "state", "chain"])
def test_missing_store_api_does_not_create_files(tmp_path: Path, query: str) -> None:
    service = ESAAService(tmp_path)
    calls = {
        "parse": lambda: parse_event_store(tmp_path),
        "verify": service.verify,
        "eligible": service.eligible,
        "state": lambda: service.task_state("T-A"),
        "chain": lambda: verify_hash_chain(tmp_path),
    }
    with pytest.raises(ESAAError) as exc:
        calls[query]()
    assert exc.value.code == "EVENT_STORE_MISSING"
    assert exc.value.penalizes_counter is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("source", ["invalid-json", "missing", "invalid-utf8", "stdin"])
def test_submit_input_errors_are_one_json_line_without_workspace_changes(
    contract_bundle: Path,
    repo_root: Path,
    source: str,
) -> None:
    _ready(contract_bundle)
    path = contract_bundle / "input.json"
    if source == "invalid-json":
        path.write_text('{"activity_event":', encoding="utf-8")
    elif source == "invalid-utf8":
        path.write_bytes(b"\xff")
    before = _snapshot(contract_bundle)
    file_arg = "-" if source == "stdin" else str(path)
    result = _cli(
        contract_bundle,
        repo_root,
        "submit",
        file_arg,
        "--actor",
        "agent-impl",
        input_text="{" if source == "stdin" else None,
    )
    _error(result, "INPUT_INVALID")
    assert _snapshot(contract_bundle) == before


@pytest.mark.parametrize("asset", ["AGENT_CONTRACT.yaml", "agent_result.schema.json"])
def test_missing_contract_is_a_workspace_error_without_writes(
    contract_bundle: Path,
    repo_root: Path,
    asset: str,
) -> None:
    _ready(contract_bundle)
    (contract_bundle / ".roadmap" / asset).unlink()
    before = _snapshot(contract_bundle)
    result = _cli(contract_bundle, repo_root, "complete", "T-A", "--actor", "agent-impl", "--check", "unit")
    _error(result, "WORKSPACE_INVALID")
    assert _snapshot(contract_bundle) == before


@pytest.mark.parametrize(
    "asset,content,code,command",
    [
        (
            "AGENT_CONTRACT.yaml",
            "a: [1",
            "WORKSPACE_INVALID",
            ["complete", "T-A", "--actor", "agent-impl", "--check", "unit"],
        ),
        (
            "agent_result.schema.json",
            "{",
            "WORKSPACE_INVALID",
            ["complete", "T-A", "--actor", "agent-impl", "--check", "unit"],
        ),
        ("RUNTIME_POLICY.yaml", "a: [1", "POLICY_INVALID", ["eligible"]),
    ],
)
def test_invalid_workspace_data_is_json_and_preserves_domain_errors(
    contract_bundle: Path,
    repo_root: Path,
    asset: str,
    content: str,
    code: str,
    command: list[str],
) -> None:
    _ready(contract_bundle)
    (contract_bundle / ".roadmap" / asset).write_text(content, encoding="utf-8")
    before = _snapshot(contract_bundle)
    _error(_cli(contract_bundle, repo_root, *command), code)
    assert _snapshot(contract_bundle) == before


@pytest.mark.parametrize("flag", ["0", "true", "1"])
def test_traceback_is_opt_in(contract_bundle: Path, repo_root: Path, flag: str) -> None:
    _ready(contract_bundle)
    result = _cli(
        contract_bundle, repo_root, "submit", "-", "--actor", "agent-impl", input_text="{", debug=flag
    )
    assert result.returncode == 1
    assert json.loads(result.stderr.splitlines()[0])["error_code"] == "INPUT_INVALID"
    assert ("Traceback" in result.stderr) is (flag == "1")


@pytest.mark.parametrize("kind", ["input", "store"])
def test_permission_failures_are_structured_without_real_permission_changes(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    _ready(contract_bundle)
    monkeypatch.setenv("ESAA_DEBUG", "0")
    source = contract_bundle / ("input.json" if kind == "input" else ".roadmap/activity.jsonl")
    original = Path.read_text

    def denied(path: Path, *args: object, **kwargs: object) -> str:
        if path == source:
            raise PermissionError("test permission denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    command = ["submit", str(source), "--actor", "agent-impl"] if kind == "input" else ["eligible"]
    assert main(["--root", str(contract_bundle), *command]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert json.loads(captured.err)["error_code"] == (
        "INPUT_INVALID" if kind == "input" else "WORKSPACE_INVALID"
    )


@pytest.mark.parametrize(
    "env", [{"ESAA_LLM_URL": ""}, {"ESAA_LLM_URL": "http://unused", "ESAA_LLM_TIMEOUT": "invalid"}]
)
def test_adapter_environment_setup_is_inside_the_error_boundary(
    contract_bundle: Path,
    repo_root: Path,
    env: dict[str, str],
) -> None:
    _ready(contract_bundle)
    before = _snapshot(contract_bundle)
    _error(
        _cli(contract_bundle, repo_root, "run", "--adapter", "http", "--steps", "1", env_extra=env),
        "WORKSPACE_INVALID",
    )
    assert _snapshot(contract_bundle) == before


def test_bootstrap_init_and_reads_remain_usable(tmp_path: Path, repo_root: Path) -> None:
    root = tmp_path / "workspace"
    result = _cli(root, repo_root, "bootstrap", "--profile", "public")
    assert result.returncode == 0, result.stderr
    assert (root / ".roadmap/AGENT_CONTRACT.yaml").is_file()
    assert not (root / ".roadmap/activity.jsonl").exists()
    before = _snapshot(root)
    _error(_cli(root, repo_root, "eligible"), "EVENT_STORE_MISSING")
    assert _snapshot(root) == before
    result = _cli(root, repo_root, "init")
    assert result.returncode == 0, result.stderr
    assert (root / ".roadmap/activity.jsonl").is_file()
    assert json.loads(_cli(root, repo_root, "verify").stdout)["verify_status"] == "ok"
    assert _cli(root, repo_root, "eligible").returncode == 0


def test_help_does_not_create_a_workspace(tmp_path: Path, repo_root: Path) -> None:
    result = _cli(tmp_path, repo_root, "--help")
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fragment", [b"{", b"\xff"])
def test_chain_corruption_remains_a_structured_failure_without_writes(
    contract_bundle: Path,
    repo_root: Path,
    fragment: bytes,
) -> None:
    _ready(contract_bundle)
    path = contract_bundle / ".roadmap/activity.jsonl"
    path.write_bytes(path.read_bytes() + fragment)
    before = _snapshot(contract_bundle)
    result = _cli(contract_bundle, repo_root, "verify", "--chain")
    assert result.returncode == 2
    assert result.stderr == ""
    output = json.loads(result.stdout)
    assert output["chain_status"] == "broken"
    assert output["error_code"] == "JSONL_INVALID"
    assert _snapshot(contract_bundle) == before


def test_programming_errors_are_not_misclassified_as_workspace_errors(
    contract_bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bug(service: ESAAService) -> None:
        raise KeyError("injected programming defect")

    monkeypatch.setattr(ESAAService, "eligible", bug)
    with pytest.raises(KeyError, match="programming defect"):
        main(["--root", str(contract_bundle), "eligible"])


def test_workspace_error_code_is_in_the_canonical_registry() -> None:
    assert WORKSPACE_INVALID in ALL_CODES
    assert WORKSPACE_INVALID in OPERATIONAL_CODES
