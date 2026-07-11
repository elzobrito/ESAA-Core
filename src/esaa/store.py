from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

from .compat import normalize_legacy_event
from .constants import (
    AGENT_CONTRACT_PATH,
    AGENT_RESULT_SCHEMA_PATH,
    CANONICAL_ACTIONS,
    EVENT_STORE_PATH,
    ISSUES_PATH,
    LESSONS_PATH,
    PROJECT_PROFILE_PATH,
    ROADMAP_PATH,
)
from .errors import CorruptedStoreError, ESAAError
from .project_profile import project_profile_view
from .provenance import resolve_runner, validate_runner_block
from .utils import ensure_parent, utc_now_iso

_CONCURRENCY_METRICS: Counter[str] = Counter()


def record_concurrency_metric(name: str, value: int = 1) -> None:
    _CONCURRENCY_METRICS[name] += int(value)


def snapshot_concurrency_metrics() -> dict[str, int]:
    return {
        "submit_retries": int(_CONCURRENCY_METRICS.get("submit_retries", 0)),
        "stale_conflicts": int(_CONCURRENCY_METRICS.get("stale_conflicts", 0)),
        "lock_takeovers": int(_CONCURRENCY_METRICS.get("lock_takeovers", 0)),
        "lock_wait_ms": int(_CONCURRENCY_METRICS.get("lock_wait_ms", 0)),
        "append_verify_failed": int(_CONCURRENCY_METRICS.get("append_verify_failed", 0)),
    }


def reset_concurrency_metrics() -> None:
    _CONCURRENCY_METRICS.clear()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_roadmap(root: Path) -> dict[str, Any] | None:
    path = root / ROADMAP_PATH
    if not path.exists():
        return None
    return _read_json(path)


def save_roadmap(root: Path, roadmap: dict[str, Any]) -> None:
    _write_json(root / ROADMAP_PATH, roadmap)


def save_issues(root: Path, issues_view: dict[str, Any]) -> None:
    _write_json(root / ISSUES_PATH, issues_view)


def save_lessons(root: Path, lessons_view: dict[str, Any]) -> None:
    _write_json(root / LESSONS_PATH, lessons_view)


def save_project_profile(root: Path, profile_view: dict[str, Any] | None) -> None:
    path = root / PROJECT_PROFILE_PATH
    if profile_view is None:
        if path.exists():
            path.unlink()
        return
    _write_json(path, profile_view)


def load_project_profile(root: Path) -> dict[str, Any] | None:
    path = root / PROJECT_PROFILE_PATH
    if not path.exists():
        return None
    profile = _read_json(path)
    if isinstance(profile, dict) and "operator" not in profile:
        profile = dict(profile)
        profile["operator"] = {"display_name": ""}
    return profile


def ensure_event_store(root: Path) -> Path:
    path = root / EVENT_STORE_PATH
    ensure_parent(path)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_event_bytes(event: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in event.items() if k != "event_hash"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_event_hash(event: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_event_bytes(event))


def _anchor_hash(lines: list[str], through_seq: int) -> str:
    if through_seq <= 0:
        return _sha256_bytes(b"")
    payload = "\n".join(lines[:through_seq]) + "\n"
    return _sha256_bytes(payload.encode("utf-8"))


def _find_anchor(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    anchors = [event for event in events if event.get("action") == "chain.anchor"]
    return anchors[-1] if anchors else None


def _validate_hash_chain(lines: list[str], events: list[dict[str, Any]]) -> None:
    anchor = _find_anchor(events)
    if anchor is None:
        return

    payload = anchor.get("payload") or {}
    anchored_through = int(payload.get("anchored_through_seq", -1))
    anchor_hash = payload.get("anchor_sha256")
    if not isinstance(anchor_hash, str) or not anchor_hash:
        raise CorruptedStoreError("CHAIN_BROKEN", "chain.anchor missing anchor_sha256")
    if anchor.get("event_seq") != anchored_through + 1:
        raise CorruptedStoreError("CHAIN_BROKEN", "chain.anchor must immediately follow anchored events")
    if _anchor_hash(lines, anchored_through) != anchor_hash:
        raise CorruptedStoreError("CHAIN_BROKEN", "anchor hash mismatch")

    prev_hash = anchor_hash
    for event in events:
        if event["event_seq"] <= anchor["event_seq"]:
            continue
        declared_prev = event.get("prev_event_hash")
        declared_hash = event.get("event_hash")
        if declared_prev != prev_hash:
            raise CorruptedStoreError("CHAIN_BROKEN", f"prev_event_hash mismatch at seq {event['event_seq']}")
        if not isinstance(declared_hash, str) or declared_hash != compute_event_hash(event):
            raise CorruptedStoreError("CHAIN_BROKEN", f"event_hash mismatch at seq {event['event_seq']}")
        prev_hash = declared_hash


def _prepare_events_for_append(
    current_events: list[dict[str, Any]], new_events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    prepared = [dict(event) for event in new_events]
    chain_events = current_events + prepared
    anchor = _find_anchor(chain_events)

    prev_hash: str | None = None
    if anchor is not None:
        prev_hash = str((anchor.get("payload") or {}).get("anchor_sha256"))
        for event in chain_events:
            if event["event_seq"] > anchor["event_seq"] and event.get("event_hash"):
                prev_hash = event["event_hash"]

    for event in prepared:
        payload = event.get("payload")
        if event.get("action") == "review" and isinstance(payload, dict) and "_reviewer_role" in payload:
            event["reviewer_role"] = payload.pop("_reviewer_role")
        if anchor is not None and event["event_seq"] > anchor["event_seq"]:
            event["prev_event_hash"] = prev_hash
            event["event_hash"] = compute_event_hash(event)
            prev_hash = event["event_hash"]
    return prepared


def verify_hash_chain(root: Path) -> dict[str, Any]:
    path = ensure_event_store(root)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        events = parse_event_store(root)
    except CorruptedStoreError as exc:
        return {"chain_status": "broken", "error_code": exc.code, "error_message": exc.message}
    anchor = _find_anchor(events)
    if anchor is None:
        return {"chain_status": "unanchored", "last_event_seq": events[-1]["event_seq"] if events else 0}
    return {
        "chain_status": "ok",
        "anchored_through_seq": anchor["payload"].get("anchored_through_seq"),
        "anchor_sha256": anchor["payload"].get("anchor_sha256"),
        "last_event_seq": events[-1]["event_seq"] if events else 0,
    }


def init_hash_chain(root: Path, force: bool = False) -> dict[str, Any]:
    path = ensure_event_store(root)
    events = parse_event_store(root)
    if _find_anchor(events) is not None and not force:
        raise ESAAError("CHAIN_ALREADY_ANCHORED", "event store already has chain.anchor")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    anchored_through = events[-1]["event_seq"] if events else 0
    payload = {
        "anchored_through_seq": anchored_through,
        "anchor_sha256": _anchor_hash(lines, anchored_through),
    }
    event_seq = next_event_seq(events)
    event = {
        "schema_version": "0.4.1",
        "event_id": f"EV-{event_seq:08d}",
        "event_seq": event_seq,
        "ts": utc_now_iso(),
        "actor": "orchestrator",
        "runner": resolve_runner(),
        "action": "chain.anchor",
        "payload": payload,
    }
    append_events(root, [event])
    return {"status": "anchored", "event_id": event["event_id"], **payload}


def parse_event_store(root: Path) -> list[dict[str, Any]]:
    path = ensure_event_store(root)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_seq = 0

    for idx, line in enumerate(lines, start=1):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorruptedStoreError("JSONL_INVALID", f"invalid JSON at line {idx}: {exc}") from exc

        event = normalize_legacy_event(raw)

        if not isinstance(event.get("event_seq"), int):
            raise CorruptedStoreError("EVENT_SEQ_INVALID", f"event_seq missing/invalid at line {idx}")
        if event["event_seq"] != last_seq + 1:
            raise CorruptedStoreError(
                "EVENT_SEQ_NON_MONOTONIC",
                f"expected event_seq={last_seq + 1}, got {event['event_seq']}",
            )
        last_seq = event["event_seq"]

        if "event_id" not in event:
            event["event_id"] = f"LEGACY-EV-{event['event_seq']:08d}"
        if event["event_id"] in seen_ids:
            raise CorruptedStoreError("EVENT_ID_DUPLICATE", f"duplicate event_id {event['event_id']}")
        seen_ids.add(event["event_id"])

        required = ("schema_version", "event_id", "event_seq", "ts", "actor", "action", "payload")
        missing = [k for k in required if k not in event]
        if missing:
            raise CorruptedStoreError("EVENT_MISSING_FIELDS", f"missing fields: {', '.join(missing)}")

        if event["action"] not in CANONICAL_ACTIONS:
            raise CorruptedStoreError("UNKNOWN_ACTION", f"unknown action in event store: {event['action']}")

        # G08/PROV-01: bloco runner e opcional (legado nao tem), mas se presente deve ser valido
        if "runner" in event and event["runner"] is not None:
            try:
                validate_runner_block(event["runner"])
            except ESAAError as exc:
                raise CorruptedStoreError("RUNNER_INVALID", f"line {idx}: {exc}") from exc

        events.append(event)

    _validate_hash_chain(lines, events)
    return events


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _lock_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_lock_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read_lock_metadata(lock_path: Path) -> dict[str, Any] | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _metadata_age_seconds(lock_path: Path, metadata: dict[str, Any] | None) -> float:
    if metadata is not None:
        ts = _parse_lock_timestamp(metadata.get("acquired_at"))
        if ts is not None:
            return max(0.0, time.time() - ts)
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return 0.0


def _takeover_lock(lock_path: Path, reason: str, metadata: dict[str, Any] | None) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    record_concurrency_metric("lock_takeovers")
    warning = {
        "code": "LOCK_TAKEOVER",
        "lock_path": str(lock_path),
        "reason": reason,
        "metadata": metadata or {},
    }
    print(json.dumps(warning, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)


def _should_takeover_lock(
    lock_path: Path, lock_max_age: float
) -> tuple[bool, str | None, dict[str, Any] | None]:
    metadata = _read_lock_metadata(lock_path)
    age = _metadata_age_seconds(lock_path, metadata)
    hostname = socket.gethostname()
    if metadata is None:
        if age >= lock_max_age:
            return True, "invalid_metadata_ttl_expired", metadata
        return False, None, metadata

    lock_host = str(metadata.get("hostname") or "")
    try:
        pid = int(metadata.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0

    if lock_host == hostname:
        if not _pid_is_alive(pid):
            return True, "dead_local_pid", metadata
        return False, None, metadata

    if age >= lock_max_age:
        return True, "cross_host_ttl_expired", metadata
    return False, None, metadata


def _acquire_store_lock(
    path: Path,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
    lock_max_age: float = 120.0,
) -> Path:
    lock_path = _lock_path(path)
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            metadata = {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "runner_id": resolve_runner().get("runner_id"),
                "acquired_at": _lock_timestamp(),
            }
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n")
            record_concurrency_metric("lock_wait_ms", int((time.monotonic() - started) * 1000))
            return lock_path
        except FileExistsError as exc:
            should_takeover, reason, metadata = _should_takeover_lock(lock_path, lock_max_age)
            if should_takeover and reason is not None:
                _takeover_lock(lock_path, reason, metadata)
                continue
            if time.monotonic() >= deadline:
                record_concurrency_metric("lock_wait_ms", int((time.monotonic() - started) * 1000))
                raise ESAAError("STORE_LOCK_TIMEOUT", f"timed out waiting for {lock_path}") from exc
            time.sleep(retry_interval)


def _release_store_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _verify_appended_lines(path: Path, expected_lines: list[str]) -> None:
    if not expected_lines:
        return
    try:
        actual_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        record_concurrency_metric("append_verify_failed")
        raise ESAAError("APPEND_VERIFY_FAILED", f"failed to re-read appended events: {exc}") from exc
    if actual_lines[-len(expected_lines) :] != expected_lines:
        record_concurrency_metric("append_verify_failed")
        raise ESAAError("APPEND_VERIFY_FAILED", "read-after-write verification did not match appended events")


def append_events(
    root: Path,
    events: list[dict[str, Any]],
    lock_timeout: float = 10.0,
    retry_interval: float = 0.05,
    lock_max_age: float = 120.0,
) -> None:
    if not events:
        return
    path = ensure_event_store(root)
    lock_path = _acquire_store_lock(
        path, timeout=lock_timeout, retry_interval=retry_interval, lock_max_age=lock_max_age
    )
    try:
        current_events = parse_event_store(root)
        prepared = _prepare_events_for_append(current_events, events)
        serialized_lines = [
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in prepared
        ]
        existing = path.read_bytes()
        needs_sep = bool(existing) and not existing.endswith(b"\n")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if needs_sep:
                handle.write("\n")
            for line in serialized_lines:
                handle.write(line + "\n")
        _verify_appended_lines(path, serialized_lines)
    finally:
        _release_store_lock(lock_path)


def next_event_seq(events: list[dict[str, Any]]) -> int:
    if not events:
        return 1
    return int(events[-1]["event_seq"]) + 1


def load_agent_contract(root: Path) -> dict[str, Any]:
    import yaml

    path = root / AGENT_CONTRACT_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_agent_result_schema(root: Path) -> dict[str, Any]:
    path = root / AGENT_RESULT_SCHEMA_PATH
    return _read_json(path)


def require_task(roadmap: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in roadmap.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    raise ESAAError("TASK_NOT_FOUND", f"task_id not found: {task_id}")


def append_transactional(
    root: Path,
    build_events_fn,
    expected_first_seq: int | None = None,
    expected_projection_hash: str | None = None,
    timeout: float = 30.0,
    lock_max_age: float = 120.0,
):
    """FIX-1806 - Serializable append: parse + validate + decide seq + append + project
    sob o mesmo lock. Elimina TOCTOU entre leitura e write.

    build_events_fn(current_events: list[dict]) -> list[dict]
        Recebe os eventos atuais (sob o lock) e devolve a lista de novos eventos
        a appendar. Deve atribuir event_seq corretos baseados em current_events.

    Raises:
        ESAAError(STALE_STATE_SEQ): expected_first_seq != next_event_seq atual
        ESAAError(STALE_STATE_HASH): expected_projection_hash != hash atual
        ESAAError(STORE_LOCK_TIMEOUT): lock nao adquirido em timeout
    Returns:
        dict com last_event_seq, projection_hash_sha256, events_appended.
    """
    from .projector import materialize  # lazy import: evita ciclo

    path = ensure_event_store(root)
    lock_path = _acquire_store_lock(path, timeout=timeout, retry_interval=0.05, lock_max_age=lock_max_age)
    try:
        events = parse_event_store(root)

        if expected_first_seq is not None:
            actual_next = next_event_seq(events)
            if actual_next != expected_first_seq:
                raise ESAAError(
                    "STALE_STATE_SEQ",
                    f"expected_first_seq={expected_first_seq} actual={actual_next}",
                )

        if expected_projection_hash is not None:
            cur_roadmap, _, _ = materialize(events)
            cur_hash = cur_roadmap["meta"]["run"]["projection_hash_sha256"]
            if cur_hash != expected_projection_hash:
                raise ESAAError(
                    "STALE_STATE_HASH",
                    f"expected_hash={expected_projection_hash[:12]}... actual={cur_hash[:12]}...",
                )

        new_events = _prepare_events_for_append(events, build_events_fn(events))
        if not new_events:
            roadmap, _, _ = materialize(events)
            return {
                "last_event_seq": roadmap["meta"]["run"]["last_event_seq"],
                "projection_hash_sha256": roadmap["meta"]["run"]["projection_hash_sha256"],
                "events_appended": 0,
            }

        # Validacao via materialize antes de persistir
        final_events = events + new_events
        final_roadmap, final_issues, final_lessons = materialize(final_events)
        final_project_profile = project_profile_view(final_events)

        # Append (reentrante sob lock atual; usa a logica de newline-guard)
        serialized_lines = [
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in new_events
        ]
        existing = path.read_bytes()
        needs_sep = bool(existing) and not existing.endswith(b"\n")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if needs_sep:
                handle.write("\n")
            for line in serialized_lines:
                handle.write(line + "\n")
        _verify_appended_lines(path, serialized_lines)

        save_roadmap(root, final_roadmap)
        save_issues(root, final_issues)
        save_lessons(root, final_lessons)
        save_project_profile(root, final_project_profile)
        return {
            "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],
            "projection_hash_sha256": final_roadmap["meta"]["run"]["projection_hash_sha256"],
            "events_appended": len(new_events),
        }
    finally:
        _release_store_lock(lock_path)
