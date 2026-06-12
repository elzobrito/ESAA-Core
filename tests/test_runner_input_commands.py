from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from esaa.cli import main
from esaa.service import ESAAService


def _run_cli(root: Path, *args: str) -> dict:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["--root", str(root), *args])
    assert code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue())


def _commands_profile(root: Path) -> Path:
    profile = root / "runtime-capabilities.yaml"
    profile.write_text(
        """
schema_version: "0.1"
command_surfaces:
  powershell:
    available: true
  wsl_ubuntu:
    available: true
    invocation: "bash -lc '<command>'"
    verified_tools:
      grep: /usr/bin/grep
      sed: /usr/bin/sed
windows_path_tools:
  search_and_files:
    - rg
    - jq
  php:
    - php
    - composer
recommended_agent_rules:
  - "Use rg for repository text search when available."
  - "Use bash -lc when GNU semantics matter."
""".lstrip(),
        encoding="utf-8",
    )
    return profile


def test_input_commands_validate_summarizes_profile(contract_bundle: Path) -> None:
    profile = _commands_profile(contract_bundle)

    result = _run_cli(contract_bundle, "input", "commands", "validate", str(profile))

    assert result["status"] == "valid"
    assert result["input_type"] == "commands"
    assert result["summary"]["command_surfaces"] == ["powershell", "wsl_ubuntu"]
    assert result["summary"]["available_tools"] == ["composer", "jq", "php", "rg"]
    assert result["summary"]["wsl_tools"] == ["grep", "sed"]


def test_input_commands_register_and_show_use_runner_id(contract_bundle: Path) -> None:
    profile = _commands_profile(contract_bundle)

    registered = _run_cli(
        contract_bundle,
        "--runner",
        "codex",
        "input",
        "commands",
        "register",
        str(profile),
    )

    assert registered["status"] == "registered"
    assert registered["runner_id"] == "codex"
    assert registered["path"] == ".roadmap/runner-inputs/commands/codex.yaml"
    assert (contract_bundle / ".roadmap/runner-inputs/commands/codex.yaml").exists()

    shown = _run_cli(contract_bundle, "--runner", "codex", "input", "commands", "show")
    assert shown["status"] == "registered"
    assert shown["runner_id"] == "codex"
    assert shown["summary"]["available_tools"] == ["composer", "jq", "php", "rg"]


def test_dispatch_context_includes_registered_runtime_capabilities(contract_bundle: Path) -> None:
    svc = ESAAService(contract_bundle)
    svc.init(force=True)
    profile = _commands_profile(contract_bundle)
    _run_cli(contract_bundle, "--runner", "codex", "input", "commands", "register", str(profile))
    _run_cli(contract_bundle, "--runner", "codex", "claim", "T-1000", "--actor", "agent-spec")

    context = _run_cli(contract_bundle, "--runner", "codex", "dispatch-context", "T-1000")

    assert context["runtime_capabilities"] == {
        "runner_id": "codex",
        "command_surfaces": ["powershell", "wsl_ubuntu"],
        "available_tools": ["composer", "jq", "php", "rg"],
        "wsl_tools": ["grep", "sed"],
        "recommended_agent_rules": [
            "Use rg for repository text search when available.",
            "Use bash -lc when GNU semantics matter.",
        ],
    }
