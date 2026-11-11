"""AUD-O1-080 (FUN-01) - RUNTIME_POLICY validada contra o schema do pacote, falhando fechado."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from esaa import cli
from esaa.bootstrap import bootstrap_workspace
from esaa.errors import ESAAError
from esaa.reject_codes import ALL_CODES, POLICY_INVALID
from esaa.runtime_policy import (
    DEFAULT_POLICY,
    POLICY_SCHEMA_PATH,
    load_policy,
    review_authorization_mode,
    review_runner_separation_mode,
    runner_validation_mode,
    validate_policy,
)
from esaa.service import ESAAService

RESERVED = "x-esaa-reserved"
METADATA = "x-esaa-metadata"


def _schema() -> dict[str, Any]:
    return json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))


def _write(root: Path, text: str) -> Path:
    path = root / ".roadmap" / "RUNTIME_POLICY.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _invalid(root: Path, text: str) -> ESAAError:
    _write(root, text)
    with pytest.raises(ESAAError) as exc:
        load_policy(root)
    assert exc.value.code == POLICY_INVALID
    assert ".roadmap/RUNTIME_POLICY.yaml" in exc.value.message
    return exc.value


def _schema_node(path: tuple[str, ...]) -> dict[str, Any] | None:
    """No do schema para um caminho de chaves; None se a chave nao existe. Para em no reservado."""
    node = _schema()
    for key in path:
        if node.get(RESERVED):
            return node
        node = (node.get("properties") or {}).get(key)
        if node is None:
            return None
    return node


def _leaf_paths(data: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if not isinstance(data, dict):
        return [prefix]
    out: list[tuple[str, ...]] = []
    for key, value in data.items():
        out.extend(_leaf_paths(value, (*prefix, str(key))))
    return out


def _schema_leaves(
    node: dict[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    if node.get(RESERVED) or "properties" not in node:
        return [(prefix, node)]
    out: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    for key, child in node["properties"].items():
        out.extend(_schema_leaves(child, (*prefix, key)))
    return out


def test_code_registered_and_schema_is_packaged(repo_root: Path) -> None:
    assert POLICY_INVALID in ALL_CODES
    assert POLICY_SCHEMA_PATH.is_file()
    assert POLICY_SCHEMA_PATH.parent.name == "templates"
    assert 'esaa = ["templates/*"' in (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert _schema()["additionalProperties"] is False


def test_absent_policy_uses_defaults_and_empty_file_is_valid(tmp_path: Path) -> None:
    assert load_policy(tmp_path) is DEFAULT_POLICY
    validate_policy(dict(DEFAULT_POLICY))
    for text in ("", "# so comentario\n", "{}\n"):
        _write(tmp_path, text)
        assert load_policy(tmp_path) == {}


def test_active_repository_policy_stays_valid(repo_root: Path) -> None:
    policy = load_policy(repo_root)

    assert review_authorization_mode(policy) == "qa_role"
    assert runner_validation_mode(policy) == "permissive"
    assert review_runner_separation_mode(policy) == "off"


@pytest.mark.parametrize("profile", ["public", "production"])
def test_bootstrapped_policy_is_valid(tmp_path: Path, profile: str) -> None:
    bootstrap_workspace(tmp_path, profile=profile)

    policy = load_policy(tmp_path)

    assert policy["review_authorization"] == "qa_role"
    assert not (tmp_path / ".roadmap" / "runtime_policy.schema.json").exists()  # schema fica no pacote


@pytest.mark.parametrize(
    ("text", "where"),
    [
        ('review_authorization: "weird"\n', "review_authorization"),
        ('runner_validation: "strcit"\n', "runner_validation"),
        ("runner_validation: true\n", "runner_validation"),
        ('review_runner_separation: "enforced"\n', "review_runner_separation"),
        ("review_runner_separation: 1\n", "review_runner_separation"),
        ('attempt_lifecycle:\n  ttl: "30 minutes"\n', "attempt_lifecycle/ttl"),
        ('attempt_limits:\n  cooldown_between_attempts: "2m"\n', "attempt_limits/cooldown_between_attempts"),
        ("attempt_limits:\n  max_attempts_per_task: 0\n", "attempt_limits/max_attempts_per_task"),
        ('attempt_limits:\n  max_attempts_per_task: "3"\n', "attempt_limits/max_attempts_per_task"),
        ("concurrency:\n  submit_retries: -1\n", "concurrency/submit_retries"),
        ('concurrency:\n  lock_max_age: "two minutes"\n', "concurrency/lock_max_age"),
        ("resource_limits:\n  max_file_updates: 0\n", "resource_limits/max_file_updates"),
        ('resource_limit_caps:\n  max_bytes_total: "8MiB"\n', "resource_limit_caps/max_bytes_total"),
        ("external_effects:\n  allow_glob_wildcard: 1\n", "external_effects/allow_glob_wildcard"),
        ('external_effects:\n  allowed_roots: "../outro"\n', "external_effects/allowed_roots"),
        ("attempt_limits: 3\n", "attempt_limits"),
    ],
)
def test_invalid_value_fails_closed(tmp_path: Path, text: str, where: str) -> None:
    error = _invalid(tmp_path, text)

    assert f" {where}: " in error.message


@pytest.mark.parametrize(
    ("text", "key", "where"),
    [
        ('review_autorization: "qa_role"\n', "review_autorization", "<root>"),
        ("attempt_limits:\n  max_attempts: 3\n", "max_attempts", "attempt_limits"),
        ("resource_limits:\n  max_files: 3\n", "max_files", "resource_limits"),
        ("external_effects:\n  allow_everything: true\n", "allow_everything", "external_effects"),
        ("concurrency:\n  retries: 2\n", "retries", "concurrency"),
    ],
)
def test_unknown_key_fails_closed(tmp_path: Path, text: str, key: str, where: str) -> None:
    error = _invalid(tmp_path, text)

    assert f" {where}: " in error.message
    assert key in error.message


@pytest.mark.parametrize("text", ["a: [1\n", "- lista\n- na raiz\n", '"so uma string"\n'])
def test_malformed_policy_fails_closed_without_traceback(tmp_path: Path, text: str) -> None:
    error = _invalid(tmp_path, text)

    assert "<root>" in error.message
    assert len(error.message) <= 200


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("enforce", "enforce"),
        ("on", "enforce"),
        (" Strict ", "enforce"),
        ("true", "enforce"),
        ("off", "off"),
        ("no", "off"),
        ("Disabled", "off"),
        ("false", "off"),
    ],
)
def test_runner_separation_accepts_every_documented_spelling(tmp_path: Path, raw: str, expected: str) -> None:
    quoted = _write(tmp_path, f'review_runner_separation: "{raw}"\n')
    assert review_runner_separation_mode(load_policy(tmp_path)) == expected

    # Sem aspas, YAML 1.1 converte on/off/yes/no/true/false em booleano; continua valido.
    quoted.write_text(f"review_runner_separation: {raw.strip()}\n", encoding="utf-8")
    assert review_runner_separation_mode(load_policy(tmp_path)) == expected


def test_valid_full_policy_is_accepted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
version: "0.4.1"
review_authorization: "owner"
review_runner_separation: "enforce"
runner_validation: "strict"
attempt_lifecycle: {ttl: "PT1H30M"}
attempt_limits: {max_attempts_per_task: 5, cooldown_between_attempts: "PT10S"}
concurrency: {submit_retries: 0, retry_backoff: 0.5, lock_max_age: "PT2M"}
resource_limits: {max_file_updates: 8, max_bytes_per_update: 1024, max_bytes_total: 4096}
resource_limit_caps: {max_file_updates: 64, max_bytes_per_update: 4194304, max_bytes_total: 8388608}
external_effects: {allowed_roots: ["../alvo"], allow_glob_wildcard: false}
""",
    )

    policy = load_policy(tmp_path)

    assert runner_validation_mode(policy) == "strict"
    assert review_authorization_mode(policy) == "owner"


def test_reserved_blocks_are_accepted_whatever_their_content(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
attempt_lifecycle:
  on_ttl_exceeded: {emit_event: "qualquer", extra: 1}
attempt_limits:
  on_limit_exceeded: "texto livre"
issue_escalation: {rules: [{severity: "critical", action: "halt_pipeline"}], futuro: true}
verify_policy: []
""",
    )

    assert set(load_policy(tmp_path)) == {
        "attempt_lifecycle",
        "attempt_limits",
        "issue_escalation",
        "verify_policy",
    }


def test_inventory_every_template_key_is_implemented_or_reserved(repo_root: Path) -> None:
    """Aceite: nenhuma chave do template fica sem leitura no codigo, salvo as marcadas como reservadas."""
    sources = {
        path.name: path.read_text(encoding="utf-8") for path in (repo_root / "src" / "esaa").glob("*.py")
    }

    def read_by_code(key: str) -> list[str]:
        literal = re.compile(rf"""["']{re.escape(key)}["']""")
        return sorted(name for name, text in sources.items() if literal.search(text))

    template = yaml.safe_load(
        (repo_root / "src" / "esaa" / "templates" / "RUNTIME_POLICY.yaml").read_text(encoding="utf-8")
    )
    reserved_in_template: set[tuple[str, ...]] = set()
    for path in _leaf_paths(template):
        node = _schema_node(path)
        assert node is not None, f"template key missing from schema: {'/'.join(path)}"
        if node.get(RESERVED):
            reserved_in_template.add(
                path[:2] if path[0] in {"attempt_lifecycle", "attempt_limits"} else path[:1]
            )
            continue
        if node.get(METADATA):
            continue
        assert read_by_code(path[-1]), f"template key is not read by any module: {'/'.join(path)}"

    assert reserved_in_template == {
        ("attempt_lifecycle", "on_ttl_exceeded"),
        ("attempt_limits", "on_limit_exceeded"),
        ("issue_escalation",),
        ("verify_policy",),
    }

    # Honestidade do schema: toda chave nao reservada precisa ser lida pelo codigo, e toda
    # chave reservada precisa dizer isso na descricao e nao ser lida por nenhum modulo.
    for path, node in _schema_leaves(_schema()):
        key = path[-1]
        if node.get(RESERVED):
            assert node["description"].startswith("reservado: sem efeito nesta versao"), path
            assert read_by_code(key) == [], f"reserved key is read by code: {'/'.join(path)}"
        elif not node.get(METADATA):
            assert read_by_code(key), f"schema key is not read by any module: {'/'.join(path)}"


def test_template_marks_reserved_blocks(repo_root: Path) -> None:
    text = (repo_root / "src" / "esaa" / "templates" / "RUNTIME_POLICY.yaml").read_text(encoding="utf-8")

    assert text.count("# RESERVADO: aceito pelo schema, sem efeito nesta versao do runtime.") == 4
    assert "POLICY_INVALID" in text


def _workspace(root: Path, repo_root: Path) -> ESAAService:
    shutil.copy2(
        repo_root / "src" / "esaa" / "templates" / "agents_swarm.yaml",
        root / ".roadmap" / "agents_swarm.yaml",
    )
    service = ESAAService(root)
    service.init(force=True)
    service.create_task("T-A", "impl", "base", outputs=["src/a.txt"])
    return service


def test_invalid_policy_blocks_writes_but_not_reads(
    contract_bundle: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(contract_bundle, repo_root)
    _write(contract_bundle, 'review_runner_separation: "enforced"\n')
    root = str(contract_bundle)
    before = (contract_bundle / ".roadmap" / "activity.jsonl").read_text(encoding="utf-8")
    capsys.readouterr()

    failing = [
        ["claim", "T-A", "--actor", "agent-impl"],
        ["eligible"],
        ["task", "create", "T-B", "--kind", "impl", "--title", "t", "--output", "src/b.txt"],
        ["reject", "T-A", "--error-code", "X", "--source-action", "claim", "--message", "m"],
    ]
    for argv in failing:
        assert cli.main(["--root", root, *argv]) == 1, argv
        captured = capsys.readouterr()
        assert '"error_code": "POLICY_INVALID"' in captured.err, argv
        assert "Traceback" not in captured.err

    for argv in (["verify"], ["state", "T-A"], ["dispatch-context", "T-A"], ["task", "list"], ["project"]):
        assert cli.main(["--root", root, *argv]) == 0, argv
        capsys.readouterr()

    assert (contract_bundle / ".roadmap" / "activity.jsonl").read_text(encoding="utf-8") == before


def test_fixing_the_policy_restores_the_workflow(contract_bundle: Path, repo_root: Path) -> None:
    _workspace(contract_bundle, repo_root)
    _write(contract_bundle, 'runner_validation: "strcit"\n')
    with pytest.raises(ESAAError) as exc:
        ESAAService(contract_bundle).claim_task("T-A", actor="agent-impl")
    assert exc.value.code == POLICY_INVALID

    _write(contract_bundle, 'runner_validation: "permissive"\n')

    assert ESAAService(contract_bundle).claim_task("T-A", actor="agent-impl")["status"] == "accepted"
