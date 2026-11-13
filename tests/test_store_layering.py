from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

from esaa.cli import _build_parser
from esaa.cli_handlers import CLI_HANDLERS

ALLOWED_ESAA_STORE_IMPORTS = {
    "constants",
    "durable_io",
    "errors",
    "reject_codes",
    "utils",
}


def _walk_parser_commands(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    subparsers = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not subparsers:
        return {prefix} if prefix else set()
    commands: set[tuple[str, ...]] = set()
    for sp in subparsers:
        for name, sub in sp.choices.items():
            commands |= _walk_parser_commands(sub, prefix + (name,))
    return commands


def test_store_has_no_domain_imports_ast() -> None:
    store_path = Path(__file__).resolve().parents[1] / "src" / "esaa" / "store.py"
    tree = ast.parse(store_path.read_text(encoding="utf-8"), filename=str(store_path))

    forbidden: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "esaa" or alias.name.startswith("esaa."):
                    sub = alias.name.split(".")[1] if "." in alias.name else ""
                    if sub not in ALLOWED_ESAA_STORE_IMPORTS:
                        forbidden.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                if mod not in ALLOWED_ESAA_STORE_IMPORTS:
                    forbidden.append((node.lineno, f".{mod}"))
            elif mod == "esaa" or mod.startswith("esaa."):
                sub = mod.split(".")[1] if "." in mod else ""
                if sub not in ALLOWED_ESAA_STORE_IMPORTS:
                    forbidden.append((node.lineno, mod))

    assert forbidden == [], f"forbidden domain imports in store.py: {forbidden}"


def test_cli_handlers_cover_all_parser_subcommands() -> None:
    parser_commands = _walk_parser_commands(_build_parser())
    missing = sorted(parser_commands - set(CLI_HANDLERS))
    assert missing == [], f"CLI_HANDLERS missing subcommands: {missing}"


def test_isolated_subprocess_imports() -> None:
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    for module_name in ("esaa.store", "esaa.events", "esaa.projector"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module_name}; print('OK')"],
            cwd=src_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"failed importing {module_name}: {proc.stderr}"
        assert proc.stdout.strip() == "OK"


def test_store_pure_io_append_and_parse_without_hooks(tmp_path: Path) -> None:
    from esaa.store import append_events, ensure_event_store, parse_event_store

    ensure_event_store(tmp_path)
    event = {
        "schema_version": "0.4.2",
        "event_id": "EV-00000001",
        "event_seq": 1,
        "ts": "2026-01-01T00:00:00Z",
        "actor": "orchestrator",
        "action": "run.start",
        "payload": {"run_id": "run-1"},
    }
    append_events(tmp_path, [event])
    loaded = parse_event_store(tmp_path)
    assert len(loaded) == 1
    assert json.loads(json.dumps(loaded[0]))["event_id"] == "EV-00000001"
