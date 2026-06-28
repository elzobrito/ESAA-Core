from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

TOTAL_REPETITIONS = 2


def _sound_commands(platform: str) -> list[list[str]]:
    if platform == "darwin":
        return [["afplay", "/System/Library/Sounds/Glass.aiff"]]
    if platform == "win32":
        return [
            [
                "powershell",
                "-c",
                "[System.Media.SystemSounds]::Exclamation.Play()",
            ]
        ]
    if platform.startswith("linux"):
        return [
            ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
            ["aplay", "/usr/share/sounds/alsa/Front_Center.wav"],
        ]
    return []


def trigger_sound(timeout: float = 2.0) -> dict[str, Any]:
    """Tenta tocar um som curto e retorna diagnostico sem quebrar o fluxo."""
    for command in _sound_commands(sys.platform):
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            return {"ok": True, "backend": command[0]}
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue

    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
        return {"ok": True, "backend": "terminal-bell"}
    except OSError as exc:
        return {"ok": False, "backend": "terminal-bell", "error": str(exc)}


def play_completion_alarm(repetitions: int = TOTAL_REPETITIONS) -> dict[str, Any]:
    """Notifica conclusao de tarefa com dois bipes por padrao."""
    total = max(1, int(repetitions))
    results = [trigger_sound() for _ in range(total)]
    return {
        "status": "played" if any(result["ok"] for result in results) else "failed",
        "repetitions": total,
        "backends": [result["backend"] for result in results],
    }


def completion_alarm_enabled_from_env() -> bool:
    return os.environ.get("ESAA_NOTIFY_ON_DONE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
