"""Tests for CLI help completeness, consistency, and exit-code documentation (AUD-O2-030)."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from esaa.cli import _build_parser, main


def _collect_missing_help(parser: argparse.ArgumentParser, prefix: str = "esaa") -> list[str]:
    missing: list[str] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            choices_actions = {
                getattr(choice_action, "dest", None): choice_action
                for choice_action in getattr(action, "_choices_actions", [])
            }
            for name, subparser in action.choices.items():
                choice_meta = choices_actions.get(name)
                sub_help = getattr(choice_meta, "help", None) if choice_meta is not None else None
                if not isinstance(sub_help, str) or not sub_help.strip():
                    missing.append(f"{prefix} {name} (subcommand)")
                missing.extend(_collect_missing_help(subparser, prefix=f"{prefix} {name}"))
            continue
        if isinstance(action, argparse._HelpAction):
            continue
        help_text = getattr(action, "help", None)
        if not isinstance(help_text, str) or not help_text.strip() or help_text is argparse.SUPPRESS:
            label = "/".join(action.option_strings) if action.option_strings else action.dest
            missing.append(f"{prefix} -> {label}")
    return missing


def _run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


def test_every_option_positional_and_subcommand_has_help() -> None:
    parser = _build_parser()
    missing = _collect_missing_help(parser)
    assert missing == [], f"Missing help text for: {missing}"


def test_missing_help_detector_reports_full_path() -> None:
    parser = argparse.ArgumentParser(prog="esaa")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("demo", help="demo command")
    cmd.add_argument("--undocumented")
    missing = _collect_missing_help(parser)
    assert missing == ["esaa demo -> --undocumented"]


def test_main_help_includes_exit_codes_and_agent_workflow() -> None:
    help_text = _build_parser().format_help()
    assert "Agent workflow:" in help_text
    assert "Exit codes:" in help_text
    assert "0  Success" in help_text
    assert "1  Domain, input or environment error" in help_text
    assert "2  Verification mismatch/corrupted" in help_text


def test_frozen_existing_commands_remain_accepted() -> None:
    parser = _build_parser()
    frozen_invocations = [
        ["bootstrap"],
        ["init"],
        ["run"],
        ["submit", "--actor", "agent-impl"],
        ["claim", "T-1", "--actor", "agent-impl"],
        ["complete", "T-1", "--actor", "agent-impl", "--check", "pytest -q"],
        ["review", "T-1", "--actor", "agent-qa", "--decision", "approve"],
        ["actor", "bootstrap", "--authorization", "auth.json"],
        [
            "actor",
            "register",
            "--actor-id",
            "a",
            "--role",
            "qa",
            "--scope",
            "s",
            "--actor-public-key",
            "00",
            "--authorization",
            "auth.json",
        ],
        ["actor", "bind-alias", "--actor-id", "a", "--alias-id", "b", "--authorization", "auth.json"],
        ["actor", "trust-import", "--pin", "pin.json"],
        ["actor", "show"],
        ["verification", "enable", "--config", "cfg.json"],
        ["verification", "show"],
        ["verification", "run", "T-1", "--candidate", "cand.json", "--actor", "agent-qa"],
        ["verification", "result", "RUN-1"],
        ["state", "T-1"],
        ["dispatch-context", "T-1"],
        ["reject", "T-1", "--error-code", "E", "--source-action", "claim", "--message", "m"],
        ["onboard"],
        ["profile", "show"],
        ["task", "list"],
        ["task", "release", "T-1", "--reason", "stale"],
        ["task", "create", "T-1", "--kind", "impl", "--title", "t"],
        ["task", "amend", "T-1", "--title", "t"],
        ["task", "set-limits", "T-1", "--max-file-bytes", "10", "--reason", "r", "--authorized-by", "op"],
        ["contract", "migrate"],
        ["contract", "revert", "--from", "bak"],
        [
            "issue",
            "report",
            "T-1",
            "--actor",
            "a",
            "--issue-id",
            "I-1",
            "--severity",
            "low",
            "--title",
            "t",
            "--symptom",
            "s",
            "--repro-step",
            "r",
        ],
        ["issue", "resolve", "--issue-id", "I-1"],
        ["hotfix", "create", "--issue-id", "I-1", "--fixes", "T-1"],
        ["activity", "list"],
        ["activity", "clear", "--dry-run"],
        ["process"],
        ["project"],
        ["verify"],
        ["verify", "--chain"],
        ["chain", "init"],
        ["chain", "verify"],
        ["store", "repair"],
        ["status"],
        ["eligible"],
        ["metrics"],
        ["input", "binary", "T-1", "src.bin", "--actor", "a", "--size", "1", "--sha256", "00"],
        ["input", "commands", "validate", "cmd.yaml"],
        ["input", "commands", "register", "cmd.yaml"],
        ["input", "commands", "show"],
        ["plugin", "list"],
        ["plugin", "new", "p1"],
        ["plugin", "validate", "p1"],
        ["plugin", "doctor", "p1"],
        ["plugin", "install", "p1"],
        ["plugin", "remove", "p1"],
        ["plugin", "status"],
        ["roadmap", "list"],
        ["roadmap", "status"],
        ["roadmap", "activate", "p1"],
        ["roadmap", "pause", "p1"],
        ["roadmap", "resume", "p1"],
        ["roadmap", "deactivate", "p1"],
        ["plugin-status"],
        ["effects", "recover"],
        ["runner", "metrics"],
        ["scenario", "hotfix"],
        ["lesson", "list"],
        ["lesson", "approve", "LES-1", "--reason", "ok"],
        ["lesson", "reject", "LES-1", "--reason", "no"],
        ["vocabulary"],
        ["snapshot", "--before", "1"],
        ["replay"],
    ]
    for argv in frozen_invocations:
        ns = parser.parse_args(argv)
        assert ns.command == argv[0]


def test_chain_verify_matches_verify_chain_across_states(tmp_path: Path) -> None:
    unanchored = tmp_path / "unanchored"
    unanchored.mkdir()
    assert _run_cli(["--root", str(unanchored), "init"])[0] == 0
    c1, out1 = _run_cli(["--root", str(unanchored), "chain", "verify"])
    c2, out2 = _run_cli(["--root", str(unanchored), "verify", "--chain"])
    assert c1 == c2 == 0
    assert out1 == out2

    anchored = tmp_path / "anchored"
    anchored.mkdir()
    assert _run_cli(["--root", str(anchored), "init", "--with-chain"])[0] == 0
    c3, out3 = _run_cli(["--root", str(anchored), "chain", "verify"])
    c4, out4 = _run_cli(["--root", str(anchored), "verify", "--chain"])
    assert c3 == c4 == 0
    assert out3 == out4

    activity_path = anchored / ".roadmap" / "activity.jsonl"
    lines = activity_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["actor"] = "tampered-actor"
    lines[0] = json.dumps(first)
    activity_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    c5, out5 = _run_cli(["--root", str(anchored), "chain", "verify"])
    c6, out6 = _run_cli(["--root", str(anchored), "verify", "--chain"])
    assert c5 == c6 == 2
    assert out5 == out6


def test_list_commands_support_format_table_and_preserve_json(tmp_path: Path) -> None:
    assert _run_cli(["--root", str(tmp_path), "init", "--with-demo-tasks"])[0] == 0

    for cmd in (
        ["task", "list"],
        ["activity", "list"],
        ["eligible"],
        ["plugin", "list"],
        ["roadmap", "list"],
        ["lesson", "list"],
    ):
        c_def, out_def = _run_cli(["--root", str(tmp_path), *cmd])
        c_json, out_json = _run_cli(["--root", str(tmp_path), *cmd, "--format", "json"])
        c_tbl, out_tbl = _run_cli(["--root", str(tmp_path), *cmd, "--format", "table"])
        assert c_def == c_json == c_tbl == 0
        assert out_def == out_json
        assert out_tbl.strip() != ""


def test_plugin_status_and_plugin_subcommand_return_same_output(tmp_path: Path) -> None:
    assert _run_cli(["--root", str(tmp_path), "init"])[0] == 0
    c1, out1 = _run_cli(["--root", str(tmp_path), "plugin-status"])
    c2, out2 = _run_cli(["--root", str(tmp_path), "plugin", "status"])
    assert c1 == c2 == 0
    assert out1 == out2
