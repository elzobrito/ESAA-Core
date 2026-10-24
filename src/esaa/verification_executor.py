"""Docker executor: stdin archive, private tmpfs, no host mounts or network."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from typing import Any

SHELL = 'tar -xf - -C /work && cd "$1" && shift && exec "$@"'


def _docker(args: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, timeout=timeout)


def _archive(files: dict[str, bytes], stream) -> None:
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o700
            info.uid = info.gid = 65534
            tar.addfile(info, io.BytesIO(data))
    stream.seek(0)


def execute_check(check: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    name = "esaa-verification-" + uuid.uuid4().hex
    started = time.monotonic()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    result = {
        "id": check["id"],
        "image": check["image"],
        "status": "unavailable",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "container_name": name,
    }
    proc = None
    threads = []
    container_created = False

    def drain(key, pipe):
        try:
            while chunk := pipe.read(8192):
                counts[key] += len(chunk)
                room = max(0, check["log_bytes"] - len(buffers[key]))
                buffers[key].extend(chunk[:room])
        finally:
            pipe.close()

    try:
        inspected = _docker(["image", "inspect", check["image"]])
        if inspected.returncode:
            result["stderr"] = "Docker unavailable or pinned image is not local; no image was pulled"
            return result
        created = _docker(
            [
                "create",
                "--pull=never",
                "--name",
                name,
                "--label",
                "esaa.verification=true",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=65534:65534",
                "--pids-limit=" + str(check["pids_limit"]),
                "--memory=" + str(check["memory_mb"]) + "m",
                "--cpus=" + str(check["cpus"]),
                "--tmpfs=/work:rw,nosuid,size=" + str(check["workspace_mb"]) + "m,mode=1777",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
                "--log-driver=none",
                "--workdir=/work",
                "--env=HOME=/tmp",
                "--env=TMPDIR=/tmp",
                "-i",
                "--entrypoint=/bin/sh",
                check["image"],
                "-c",
                SHELL,
                "esaa",
                "/work" if check["cwd"] == "." else "/work/" + check["cwd"],
                *check["command"],
            ]
        )
        if created.returncode:
            result["stderr"] = created.stderr[: check["log_bytes"]].decode("utf-8", "replace")
            return result
        container_created = True
        with tempfile.TemporaryFile() as archive:
            _archive(files, archive)
            proc = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", name],
                stdin=archive,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for key, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                thread = threading.Thread(target=drain, args=(key, pipe), daemon=True)
                thread.start()
                threads.append(thread)
            try:
                proc.wait(timeout=check["timeout_seconds"])
                state = _docker(["inspect", "--format", "{{json .State}}", name])
                if state.returncode:
                    result["status"] = "failed"
                else:
                    state = json.loads(state.stdout)
                    result["exit_code"] = state["ExitCode"]
                    result["status"] = (
                        "passed"
                        if proc.returncode == 0
                        and state.get("Status") == "exited"
                        and not state.get("OOMKilled")
                        and state["ExitCode"] == 0
                        else "failed"
                    )
            except subprocess.TimeoutExpired:
                result["status"] = "timeout"
    except KeyboardInterrupt:
        result["status"] = "cancelled"
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        result["stderr"] = str(exc)[: check["log_bytes"]]
    finally:
        try:
            if container_created:
                cleanup = _docker(["rm", "--force", name], timeout=15)
                if cleanup.returncode:
                    result["status"] = "failed"
                    result["cleanup_error"] = True
        except (OSError, subprocess.SubprocessError):
            result["status"] = "failed"
            result["cleanup_error"] = True
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
        if any(t.is_alive() for t in threads):
            result["status"] = "failed"
            result["cleanup_error"] = True
        for key in buffers:
            if buffers[key]:
                result[key] = buffers[key].decode("utf-8", "replace")
            encoded = result[key].encode("utf-8")
            result[key] = encoded[: check["log_bytes"]].decode("utf-8", "ignore")
            result[key + "_truncated"] = counts[key] > check["log_bytes"] or len(encoded) > check["log_bytes"]
            result[key + "_bytes"] = counts[key]
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
    return result
