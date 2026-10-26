"""Applied bytes remain the verified candidate despite mutable disk stages."""

from pathlib import Path

from test_verification_executor import ready
from test_verification_gate import attest

from esaa.file_effects import commit_staged, stage_file_updates


def test_stages_with_identical_content_have_independent_ownership(tmp_path):
    first = stage_file_updates(tmp_path, [{"path": "a.py", "content": "same\n"}])
    second = stage_file_updates(tmp_path, [{"path": "b.py", "content": "same\n"}])
    assert first[0]["staged_path"] != second[0]["staged_path"]
    commit_staged(tmp_path, second)
    commit_staged(tmp_path, first)
    assert (tmp_path / "a.py").read_text() == (tmp_path / "b.py").read_text() == "same\n"


def test_commit_does_not_consume_mutable_stage_bytes(tmp_path):
    staged = stage_file_updates(tmp_path, [{"path": "a.py", "content": "approved\n"}])
    Path(staged[0]["staged_path"]).write_text("unverified\n")
    commit_staged(tmp_path, staged)
    assert (tmp_path / "a.py").read_text() == "approved\n"
    assert not list(tmp_path.glob(".esaa-apply-*"))


def test_verification_gate_applies_exact_candidate_under_stage_tampering(contract_bundle, monkeypatch):
    svc, candidate = ready(contract_bundle)
    attest(svc, candidate, monkeypatch)
    original = svc._append_events_transactionally

    def tamper(base, pending, **kwargs):
        for stage in (contract_bundle / ".roadmap/staging").glob("stage-*.tmp"):
            stage.write_text("unverified\n")
        return original(base, pending, **kwargs)

    monkeypatch.setattr(svc, "_append_events_transactionally", tamper)
    svc.submit(candidate, actor="agent-impl")
    assert (contract_bundle / "tetris.py").read_text() == "fixed\n"
    assert svc.verify()["verify_status"] == "ok"
