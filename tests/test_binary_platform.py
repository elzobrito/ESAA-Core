import hashlib
import os

import pytest

from esaa.binary_input import stage_task_input
from esaa.binary_payload import stage_binary
from esaa.errors import ESAAError
from esaa.service import ESAAService


def test_unsupported_binary_platform_rejects_before_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(ESAAError, match="POSIX secure dirfd") as exc:
        stage_binary(tmp_path, "source", tmp_path, size=0, sha256=hashlib.sha256(b"").hexdigest(), limit=0)
    assert exc.value.code == "BINARY_PLATFORM_UNSUPPORTED"
    assert not list(tmp_path.iterdir())


def test_unsupported_binary_input_has_structured_cli_error(contract_bundle, monkeypatch, capsys):
    from esaa import cli

    service = ESAAService(contract_bundle)
    service.init()
    service.create_task("A", task_kind="impl", title="binary input")
    service.claim_task("A", actor="agent-impl")
    data = b"payload"
    (contract_bundle / "source").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(ESAAError) as exc:
        stage_task_input(service, "A", "agent-impl", "source", len(data), digest)
    assert exc.value.code == "BINARY_PLATFORM_UNSUPPORTED"
    rc = cli.main(
        [
            "--root",
            str(contract_bundle),
            "input",
            "binary",
            "A",
            "source",
            "--actor",
            "agent-impl",
            "--size",
            str(len(data)),
            "--sha256",
            digest,
        ]
    )
    assert rc == 1
    assert '"error_code": "BINARY_PLATFORM_UNSUPPORTED"' in capsys.readouterr().err
    assert service.task_state("A")["task"]["status"] == "in_progress"
    assert not list((contract_bundle / ".roadmap/binary-input").rglob(digest))
