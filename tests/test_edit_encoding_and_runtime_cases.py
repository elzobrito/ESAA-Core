"""Edge cases de edits (T-2061): CRLF exato, arquivo nao-UTF-8 e runtime:// com edits.

Cobre os branches de src/esaa/edits.py sem teste dedicado, conforme o
AGENT_CONTRACT: old_string casa contra o texto UTF-8 decodificado com os
newlines exatos do arquivo (CRLF incluido — nao normalizar \\r\\n para \\n);
arquivo nao-UTF-8 e runtime:// com edits rejeitam com EDIT_INVALID.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from esaa.edits import resolve_edit_updates
from esaa.errors import ESAAError
from esaa.file_effects import STAGING_DIR
from esaa.service import ESAAService
from esaa.store import parse_event_store

TARGET = "docs/spec/T-1000.md"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _claim_spec(root: Path) -> ESAAService:
    svc = ESAAService(root)
    svc.init(force=True)
    svc.submit(
        {"activity_event": {"action": "claim", "task_id": "T-1000", "prior_status": "todo"}},
        actor="agent-spec",
    )
    return svc


def _complete_with(updates: list[dict]) -> dict:
    return {
        "activity_event": {
            "action": "complete",
            "task_id": "T-1000",
            "prior_status": "in_progress",
            "verification": {"checks": ["edge case de edit validado"]},
        },
        "file_updates": updates,
    }


def _staging_files(root: Path) -> list[Path]:
    staging = root / STAGING_DIR
    if not staging.exists():
        return []
    return [path for path in staging.rglob("*") if path.is_file()]


def _seed_bytes(root: Path, data: bytes) -> Path:
    target = root / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


# ---------------------------------------------------------------------------
# 3b — CRLF: old_string casa contra os newlines exatos e o resultado preserva CRLF
# ---------------------------------------------------------------------------


def test_edit_on_crlf_file_matches_exact_newlines_and_preserves_crlf(contract_bundle: Path) -> None:
    base = b"# Spec\r\nstatus: draft\r\nfim\r\n"
    target = _seed_bytes(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    result = svc.submit(
        _complete_with(
            [
                {
                    "path": TARGET,
                    "base_sha256": _sha_bytes(base),
                    "edits": [
                        {"old_string": "status: draft\r\n", "new_string": "status: ready\r\n"}
                    ],
                }
            ]
        ),
        actor="agent-spec",
    )

    assert result["status"] == "accepted"
    assert target.read_bytes() == b"# Spec\r\nstatus: ready\r\nfim\r\n"


def test_edit_with_lf_old_string_does_not_match_crlf_file(contract_bundle: Path) -> None:
    # Contrato: nao normalizar \r\n para \n — old_string com LF puro nao pode
    # casar num arquivo CRLF.
    base = b"# Spec\r\nstatus: draft\r\n"
    target = _seed_bytes(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {
                        "path": TARGET,
                        "base_sha256": _sha_bytes(base),
                        "edits": [
                            {"old_string": "# Spec\nstatus: draft", "new_string": "x"}
                        ],
                    }
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "EDIT_TARGET_NOT_FOUND"
    assert target.read_bytes() == base
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_edit_can_convert_crlf_segment_without_touching_other_lines(contract_bundle: Path) -> None:
    # Edicao que altera apenas o miolo mantem os CRLF das demais linhas.
    base = b"a\r\nold\r\nz\r\n"
    target = _seed_bytes(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    svc.submit(
        _complete_with(
            [
                {
                    "path": TARGET,
                    "base_sha256": _sha_bytes(base),
                    "edits": [{"old_string": "old", "new_string": "new"}],
                }
            ]
        ),
        actor="agent-spec",
    )

    assert target.read_bytes() == b"a\r\nnew\r\nz\r\n"


# ---------------------------------------------------------------------------
# 3c — arquivo nao-UTF-8: EDIT_INVALID apos base_sha256 valido (edits.py)
# ---------------------------------------------------------------------------


def test_edit_on_non_utf8_file_is_edit_invalid_without_store_or_staging_change(
    contract_bundle: Path,
) -> None:
    # 0xFF nunca e valido em UTF-8; base_sha256 correto isola o branch de decode.
    base = b"\xff\xfeconteudo \xe9 latin-1\r\n"
    target = _seed_bytes(contract_bundle, base)
    svc = _claim_spec(contract_bundle)
    before = len(parse_event_store(contract_bundle))

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {
                        "path": TARGET,
                        "base_sha256": _sha_bytes(base),
                        "edits": [{"old_string": "conteudo", "new_string": "x"}],
                    }
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "EDIT_INVALID"
    assert "not valid UTF-8" in exc.value.message
    assert target.read_bytes() == base
    assert len(parse_event_store(contract_bundle)) == before
    assert _staging_files(contract_bundle) == []


def test_non_utf8_with_wrong_base_sha_fails_base_mismatch_before_decode(
    contract_bundle: Path,
) -> None:
    # Ordem dos gates: base_sha256 divergente reporta EDIT_BASE_MISMATCH antes
    # do decode UTF-8.
    base = b"\xff\xfebytes"
    _seed_bytes(contract_bundle, base)
    svc = _claim_spec(contract_bundle)

    with pytest.raises(ESAAError) as exc:
        svc.submit(
            _complete_with(
                [
                    {
                        "path": TARGET,
                        "base_sha256": _sha_bytes(b"outros bytes"),
                        "edits": [{"old_string": "a", "new_string": "b"}],
                    }
                ]
            ),
            actor="agent-spec",
        )

    assert exc.value.code == "EDIT_BASE_MISMATCH"


# ---------------------------------------------------------------------------
# 3d — runtime:// com edits: EDIT_INVALID (edits nao suportados fora do workspace)
# ---------------------------------------------------------------------------


def test_runtime_path_with_edits_is_edit_invalid_standalone(contract_bundle: Path) -> None:
    with pytest.raises(ESAAError) as exc:
        resolve_edit_updates(
            contract_bundle,
            [
                {
                    "path": "runtime://outputs.client",
                    "base_sha256": "0" * 64,
                    "edits": [{"old_string": "a", "new_string": "b"}],
                }
            ],
        )

    assert exc.value.code == "EDIT_INVALID"
    assert "runtime://" in exc.value.message


def test_runtime_path_with_content_still_resolves_standalone(contract_bundle: Path) -> None:
    # Forma content para runtime:// segue passando pelo resolvedor de edits
    # (a validacao de boundary/external acontece depois, em outra camada).
    resolved = resolve_edit_updates(
        contract_bundle,
        [{"path": "runtime://outputs.client", "content": "payload\n"}],
    )

    assert resolved == [{"path": "runtime://outputs.client", "content": "payload\n"}]
