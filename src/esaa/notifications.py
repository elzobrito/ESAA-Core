from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

TRANSITION_MESSAGES = {
    "in_progress": "Task in progress",
    "review": "Task review",
    "done": "Task done",
}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _speech_commands(platform: str, message: str) -> list[list[str]]:
    if platform == "darwin":
        return [["say", message]]
    if platform == "win32":
        escaped = message.replace("'", "''")
        return [
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Add-Type -AssemblyName System.Speech; "
                    "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$synth.Speak('{escaped}')"
                ),
            ]
        ]
    if platform.startswith("linux"):
        return [
            ["spd-say", "--wait", message],
            ["espeak-ng", message],
            ["espeak", message],
        ]
    return []


def speak_message(message: str, timeout: float = 8.0) -> dict[str, Any]:
    """Speak a short notification message; never raise into the ESAA flow."""
    for command in _speech_commands(sys.platform, message):
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            return {"ok": True, "backend": command[0], "message": message}
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue

    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
        return {"ok": True, "backend": "terminal-bell", "message": message}
    except OSError as exc:
        return {"ok": False, "backend": "terminal-bell", "message": message, "error": str(exc)}


def play_transition_message(status: str) -> dict[str, Any]:
    message = TRANSITION_MESSAGES.get(status, f"Task {status.replace('_', ' ')}")
    result = speak_message(message)
    return {
        "status": "played" if result["ok"] else "failed",
        "backend": result["backend"],
        "message": message,
    }


def play_completion_alarm() -> dict[str, Any]:
    """Backward-compatible wrapper for completion notification callers."""
    return play_transition_message("done")


def completion_alarm_enabled_from_env() -> bool:
    return _truthy_env("ESAA_NOTIFY_ON_DONE")


def transition_messages_enabled_from_env() -> bool:
    return _truthy_env("ESAA_NOTIFY_TRANSITIONS")
