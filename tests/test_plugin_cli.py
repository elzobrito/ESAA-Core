from __future__ import annotations

import json

from esaa.cli import main


def test_plugin_cli_install_and_roadmap_activate(tmp_path, repo_root, capsys) -> None:
    assert main(["--root", str(tmp_path), "plugin", "new", "sso-client"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "plugin", "install", "./sso-client"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["status"] == "installed"

    assert main([
        "--root",
        str(tmp_path),
        "roadmap",
        "activate",
        "sso-client",
        "--execution-id",
        "default",
    ]) == 0
    activated = json.loads(capsys.readouterr().out)
    assert activated["status"] == "active"
    assert activated["execution_id"] == "default"

    assert main(["--root", str(tmp_path), "roadmap", "status", "--detail"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["roadmaps"][0]["status"] == "active"
    assert status["roadmaps"][0]["tasks"][0]["task_id"] == "sso-client-default-T-001"


def test_plugin_cli_list_available(capsys) -> None:
    assert main(["plugin", "list", "--available"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["plugins"] == []
