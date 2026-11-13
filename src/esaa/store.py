from __future__ import annotations

import ctypes
import hashlib
import json
import os
import socket
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
from .durable_io import atomic_write_bytes, sync_directory
from .errors import CorruptedStoreError, ESAAError
from .reject_codes import EVENT_STORE_MISSING
from .utils import ensure_parent


@dataclass(frozen=True)
class StoreHooks:
    """Optional domain callbacks injected into pure I/O store operations."""

    normalize_event: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    validate_runner: Callable[[Any], None] | None = None
    validate_representation: Callable[[dict[str, Any]], None] | None = None
    validate_identity_history: Callable[[Path, list[dict[str, Any]]], None] | None = None
    validate_append_event: Callable[[dict[str, Any]], None] | None = None
    prepare_activation: Callable[[Path, list[dict[str, Any]], list[dict[str, Any]]], None] | None = None
    advance_checkpoint: Callable[[Path, list[dict[str, Any]], str], Any] | None = None
    event_factory: Callable[..., dict[str, Any]] | None = None
    resolve_runner: Callable[[], dict[str, Any]] | None = None
    load_tx_state: Callable[[Path, StoreHooks | None], dict[str, Any]] | None = None
    reload_tx_state: Callable[[Path, StoreHooks | None], dict[str, Any]] | None = None
    project_tx_views: (
        Callable[
            [dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]],
            tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None],
        ]
        | None
    ) = None


_CONCURRENCY_METRICS: Counter[str] = Counter()


def record_concurrency_metric(name: str, value: int = 1) -> None:
    _CONCURRENCY_METRICS[name] += int(value)


def snapshot_concurrency_metrics() -> dict[str, int]:
    return {
        "submit_retries": int(_CONCURRENCY_METRICS.get("submit_retries", 0)),
        "stale_conflicts": int(_CONCURRENCY_METRICS.get("stale_conflicts", 0)),
        "lock_takeovers": int(_CONCURRENCY_METRICS.get("lock_takeovers", 0)),
        "lock_wait_ms": int(_CONCURRENCY_METRICS.get("lock_wait_ms", 0)),
        "lock_retries": int(_CONCURRENCY_METRICS.get("lock_retries", 0)),
        "events_appended": int(_CONCURRENCY_METRICS.get("events_appended", 0)),
        "append_verify_failed": int(_CONCURRENCY_METRICS.get("append_verify_failed", 0)),
    }


def reset_concurrency_metrics() -> None:
    _CONCURRENCY_METRICS.clear()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


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
            sync_directory(path.parent)
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
    current_events: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
    *,
    hooks: StoreHooks | None = None,
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
    if hooks is not None and hooks.validate_append_event is not None:
        for event in prepared:
            hooks.validate_append_event(event)
    return prepared


def verify_hash_chain(root: Path, *, hooks: StoreHooks | None = None) -> dict[str, Any]:
    try:
        events = parse_event_store(root, hooks=hooks)
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


def init_hash_chain(root: Path, force: bool = False, *, hooks: StoreHooks | None = None) -> dict[str, Any]:
    """Anchor and project one consistent prefix under the append transaction lock."""
    if hooks is None or hooks.event_factory is None:
        raise ESAAError("INVALID_ARGUMENT", "init_hash_chain requires StoreHooks.event_factory")
    make_event_fn = hooks.event_factory
    result: dict[str, Any] = {}

    def build_anchor(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if _find_anchor(events) is not None and not force:
            raise ESAAError("CHAIN_ALREADY_ANCHORED", "event store already has chain.anchor")
        path = root / EVENT_STORE_PATH
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        through_seq = events[-1]["event_seq"] if events else 0
        payload = {"anchored_through_seq": through_seq, "anchor_sha256": _anchor_hash(lines, through_seq)}
        event = make_event_fn(next_event_seq(events), "orchestrator", "chain.anchor", payload)
        result.update(status="anchored", event_id=event["event_id"], **payload)
        return [event]

    append_transactional(root, build_anchor, hooks=hooks)
    return result


# AUD-O1-010: digest do ultimo conteudo do event store que passou por TODA a validacao
# estrutural (JSON, sequencia, ids, acoes, runner, cadeia de hash), por caminho. Um comando
# le o log varias vezes; quando os bytes sao os mesmos, repetir essas checagens - funcoes
# puras do conteudo - nao acrescenta nada. Os eventos sao sempre decodificados de novo
# (objetos novos a cada chamada) e a validacao de identidade/trust, que depende de arquivos
# externos, roda em toda chamada.
_VALIDATED_STORE_DIGESTS: dict[str, bytes] = {}
JSONL_REPAIR_HINT = "inspect with `esaa store repair --dry-run`; only a malformed final line can be repaired"


def _normalize_validated_event(raw: dict[str, Any], hooks: StoreHooks | None = None) -> dict[str, Any]:
    event = (
        hooks.normalize_event(raw) if hooks is not None and hooks.normalize_event is not None else dict(raw)
    )
    if "event_id" not in event:
        event["event_id"] = f"LEGACY-EV-{event['event_seq']:08d}"
    return event


def _decode_jsonl_lines(lines: list[str]) -> list[dict[str, Any]] | None:
    try:
        decoded = json.loads("[" + ",".join(lines) + "]")
        return decoded if len(decoded) == len(lines) else None
    except json.JSONDecodeError:
        return None


def _validate_and_normalize_event_line(
    idx: int,
    line: str,
    raw_events: list[dict[str, Any]] | None,
    *,
    last_seq: int,
    seen_ids: set[str],
    hooks: StoreHooks | None,
    line_label: str,
) -> dict[str, Any]:
    try:
        raw = raw_events[idx - 1] if raw_events is not None else json.loads(line)
    except json.JSONDecodeError as exc:
        raise CorruptedStoreError(
            "JSONL_INVALID", f"invalid JSON {line_label} {idx}: {exc}; {JSONL_REPAIR_HINT}"
        ) from exc

    if hooks is not None and hooks.validate_representation is not None:
        try:
            hooks.validate_representation(raw)
        except CorruptedStoreError as exc:
            if exc.code == "JSONL_INVALID":
                raise CorruptedStoreError(exc.code, f"{exc.message}; {JSONL_REPAIR_HINT}") from exc
            raise

    event = (
        hooks.normalize_event(raw) if hooks is not None and hooks.normalize_event is not None else dict(raw)
    )
    if not isinstance(event.get("event_seq"), int):
        raise CorruptedStoreError("EVENT_SEQ_INVALID", f"event_seq missing/invalid {line_label} {idx}")
    if event["event_seq"] != last_seq + 1:
        raise CorruptedStoreError(
            "EVENT_SEQ_NON_MONOTONIC",
            f"expected event_seq={last_seq + 1}, got {event['event_seq']}",
        )
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
    if (
        "runner" in event
        and event["runner"] is not None
        and hooks is not None
        and hooks.validate_runner is not None
    ):
        try:
            hooks.validate_runner(event["runner"])
        except ESAAError as exc:
            raise CorruptedStoreError("RUNNER_INVALID", f"{line_label} {idx}: {exc}") from exc
    return event


def parse_event_store(root: Path, *, hooks: StoreHooks | None = None) -> list[dict[str, Any]]:
    path = root / EVENT_STORE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ESAAError(
            EVENT_STORE_MISSING,
            "event store missing; run esaa init (esaa bootstrap first if needed); no files were created",
            penalizes_counter=False,
        ) from exc
    except UnicodeDecodeError as exc:
        raise CorruptedStoreError("JSONL_INVALID", f"invalid UTF-8: {exc}; {JSONL_REPAIR_HINT}") from exc
    return parse_event_store_text(root, text, cache_key=str(path), hooks=hooks)


def parse_event_store_text(
    root: Path,
    text: str,
    *,
    cache_key: str | None = None,
    hooks: StoreHooks | None = None,
) -> list[dict[str, Any]]:
    """Validate a supplied prefix without creating, truncating or projecting files.

    Repair uses the real root so identity and external trust cannot be bypassed
    by validating a copy in an unenrolled temporary workspace.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    digest = hashlib.sha256(text.encode("utf-8")).digest()

    if cache_key is not None and _VALIDATED_STORE_DIGESTS.get(cache_key) == digest:
        known = [_normalize_validated_event(raw, hooks) for raw in json.loads("[" + ",".join(lines) + "]")]
        if hooks is not None and hooks.validate_identity_history is not None:
            hooks.validate_identity_history(root, known)
        return known

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_seq = 0
    raw_events = _decode_jsonl_lines(lines)

    for idx, line in enumerate(lines, start=1):
        event = _validate_and_normalize_event_line(
            idx,
            line,
            raw_events,
            last_seq=last_seq,
            seen_ids=seen_ids,
            hooks=hooks,
            line_label="at line",
        )
        last_seq = event["event_seq"]
        events.append(event)

    _validate_hash_chain(lines, events)
    if hooks is not None and hooks.validate_identity_history is not None:
        hooks.validate_identity_history(root, events)
    if cache_key is not None:
        _VALIDATED_STORE_DIGESTS[cache_key] = digest
    return events


def scan_event_offsets(root: Path, before: int) -> tuple[int, int]:
    """Return (last_covered_event_offset_bytes, tail_offset_bytes) for a given before_event_seq."""
    path = root / EVENT_STORE_PATH
    if not path.exists():
        raise ESAAError(
            EVENT_STORE_MISSING,
            "event store missing; run esaa init (esaa bootstrap first if needed); no files were created",
            penalizes_counter=False,
        )
    last_covered_offset = 0
    tail_offset = 0
    with path.open("rb") as handle:
        while True:
            offset = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            stripped = raw_line.strip()
            if not stripped:
                continue
            raw_obj = json.loads(stripped.decode("utf-8"))
            seq = int(raw_obj["event_seq"])
            if seq <= before:
                last_covered_offset = offset
                tail_offset = handle.tell()
            else:
                tail_offset = offset
                break
    return last_covered_offset, tail_offset


def read_event_at_offset(
    root: Path, offset_bytes: int, *, hooks: StoreHooks | None = None
) -> tuple[dict[str, Any], int]:
    """Read and normalize one JSONL event starting at offset_bytes, returning (event, next_offset)."""
    path = root / EVENT_STORE_PATH
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if offset_bytes < 0 or offset_bytes >= size:
            raise CorruptedStoreError("JSONL_INVALID", f"offset {offset_bytes} out of range (size={size})")
        handle.seek(offset_bytes)
        raw_line = handle.readline()
        next_offset = handle.tell()
    stripped = raw_line.strip()
    if not stripped:
        raise CorruptedStoreError("JSONL_INVALID", f"empty line at offset {offset_bytes}")
    try:
        raw = json.loads(stripped.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorruptedStoreError("JSONL_INVALID", f"invalid JSON at offset {offset_bytes}: {exc}") from exc
    event = (
        hooks.normalize_event(raw) if hooks is not None and hooks.normalize_event is not None else dict(raw)
    )
    return event, next_offset


def parse_event_store_tail(
    root: Path,
    offset_bytes: int,
    *,
    expected_first_seq: int,
    expected_prev_hash: str | None = None,
    hooks: StoreHooks | None = None,
) -> list[dict[str, Any]]:
    """Parse and validate only the tail of activity.jsonl starting at offset_bytes."""
    path = root / EVENT_STORE_PATH
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if offset_bytes < 0 or offset_bytes > size:
            raise CorruptedStoreError(
                "JSONL_INVALID", f"tail offset {offset_bytes} out of range (size={size})"
            )
        handle.seek(offset_bytes)
        raw_bytes = handle.read()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptedStoreError(
            "JSONL_INVALID", f"invalid UTF-8 in tail: {exc}; {JSONL_REPAIR_HINT}"
        ) from exc

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_seq = expected_first_seq - 1
    prev_hash = expected_prev_hash
    raw_events = _decode_jsonl_lines(lines)

    for idx, line in enumerate(lines, start=1):
        event = _validate_and_normalize_event_line(
            idx,
            line,
            raw_events,
            last_seq=last_seq,
            seen_ids=seen_ids,
            hooks=hooks,
            line_label="in tail line",
        )
        last_seq = event["event_seq"]
        if "event_hash" in event:
            if prev_hash is not None and event.get("prev_event_hash") != prev_hash:
                raise CorruptedStoreError(
                    "CHAIN_BROKEN", f"tail prev_hash mismatch at seq {event['event_seq']}"
                )
            prev_hash = event["event_hash"]
        events.append(event)
    return events


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _lock_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        windll = cast(Any, ctypes).windll
        handle = windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        windll.kernel32.CloseHandle(handle)
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
    *,
    runner_id: str | None = None,
) -> Path:
    lock_path = _lock_path(path)
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    resolved_runner_id = runner_id if runner_id is not None else os.environ.get("ESAA_RUNNER_ID")
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            metadata = {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "runner_id": resolved_runner_id,
                "acquired_at": _lock_timestamp(),
            }
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n")
            record_concurrency_metric("lock_wait_ms", int((time.monotonic() - started) * 1000))
            return lock_path
        except FileExistsError as exc:
            record_concurrency_metric("lock_retries")
            should_takeover, reason, existing = _should_takeover_lock(lock_path, lock_max_age)
            if should_takeover and reason is not None:
                _takeover_lock(lock_path, reason, existing)
                continue
            if time.monotonic() >= deadline:
                record_concurrency_metric("lock_wait_ms", int((time.monotonic() - started) * 1000))
                raise ESAAError("STORE_LOCK_TIMEOUT", f"timed out waiting for {lock_path}") from exc
            time.sleep(retry_interval)


def _release_store_lock(lock_path: Path, *, timeout: float = 1.0, retry_interval: float = 0.01) -> None:
    # Windows metadata readers can briefly prevent deletion of our owned lock.
    # Retry only that sharing violation, never the already-committed append.
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {32, 33} or time.monotonic() >= deadline:
                raise
            time.sleep(retry_interval)


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
    record_concurrency_metric("events_appended", len(expected_lines))


def append_events(
    root: Path,
    events: list[dict[str, Any]],
    lock_timeout: float = 10.0,
    retry_interval: float = 0.05,
    lock_max_age: float = 120.0,
    *,
    hooks: StoreHooks | None = None,
) -> None:
    if not events:
        return
    path = ensure_event_store(root)
    runner_id = (
        hooks.resolve_runner().get("runner_id")
        if hooks is not None and hooks.resolve_runner is not None
        else None
    )
    lock_path = _acquire_store_lock(
        path,
        timeout=lock_timeout,
        retry_interval=retry_interval,
        lock_max_age=lock_max_age,
        runner_id=runner_id,
    )
    try:
        current_events = parse_event_store(root, hooks=hooks)
        prepared = _prepare_events_for_append(current_events, events, hooks=hooks)
        final_events = current_events + prepared
        if hooks is not None and hooks.validate_identity_history is not None:
            hooks.validate_identity_history(root, final_events)
        if hooks is not None and hooks.prepare_activation is not None:
            hooks.prepare_activation(root, current_events, final_events)
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
            handle.flush()
            os.fsync(handle.fileno())
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


def _write_serialized_lines(path: Path, serialized_lines: list[str]) -> None:
    existing = path.read_bytes()
    needs_sep = bool(existing) and not existing.endswith(b"\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_sep:
            handle.write("\n")
        for line in serialized_lines:
            handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _verify_appended_lines(path, serialized_lines)


def _load_tx_state_for_append(root: Path, hooks: StoreHooks | None) -> dict[str, Any]:
    if hooks is not None and hooks.load_tx_state is not None:
        return hooks.load_tx_state(root, hooks)
    events = parse_event_store(root, hooks=hooks)
    return {
        "events": events,
        "using_snapshot": False,
        "current_run": {
            "last_event_seq": events[-1]["event_seq"] if events else 0,
            "projection_hash_sha256": "",
        },
    }


def _check_tx_preconditions(
    events: list[dict[str, Any]],
    current_run: dict[str, Any],
    expected_first_seq: int | None,
    expected_projection_hash: str | None,
) -> None:
    if expected_first_seq is not None:
        actual_next = next_event_seq(events)
        if actual_next != expected_first_seq:
            raise ESAAError(
                "STALE_STATE_SEQ",
                f"expected_first_seq={expected_first_seq} actual={actual_next}",
            )
    if expected_projection_hash is not None:
        cur_hash = current_run["projection_hash_sha256"]
        if cur_hash != expected_projection_hash:
            raise ESAAError(
                "STALE_STATE_HASH",
                f"expected_hash={expected_projection_hash[:12]}... actual={cur_hash[:12]}...",
            )


def _persist_tx_result(
    root: Path,
    projected_views: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None] | None,
    final_events: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
    after_append: Any,
    result_task_id: str | None,
    hooks: StoreHooks | None,
) -> dict[str, Any]:
    if projected_views is None:
        if after_append is not None:
            after_append()
        return {
            "last_event_seq": final_events[-1]["event_seq"] if final_events else 0,
            "projection_hash_sha256": "",
            "events_appended": len(new_events),
        }
    final_roadmap, final_issues, final_lessons, final_project_profile = projected_views
    save_roadmap(root, final_roadmap)
    save_issues(root, final_issues)
    save_lessons(root, final_lessons)
    save_project_profile(root, final_project_profile)
    if after_append is not None:
        after_append()
    proj_hash = final_roadmap["meta"]["run"]["projection_hash_sha256"]
    if hooks is not None and hooks.advance_checkpoint is not None:
        hooks.advance_checkpoint(root, final_events, proj_hash)
    result: dict[str, Any] = {
        "last_event_seq": final_roadmap["meta"]["run"]["last_event_seq"],
        "projection_hash_sha256": proj_hash,
        "events_appended": len(new_events),
    }
    if result_task_id is not None:
        from copy import deepcopy

        result["task"] = deepcopy(next(t for t in final_roadmap["tasks"] if t["task_id"] == result_task_id))
    return result


def append_transactional(
    root: Path,
    build_events_fn,
    expected_first_seq: int | None = None,
    expected_projection_hash: str | None = None,
    timeout: float = 30.0,
    lock_max_age: float = 120.0,
    after_append=None,
    result_task_id: str | None = None,
    *,
    hooks: StoreHooks | None = None,
):
    """FIX-1806 - Serializable append: parse + validate + decide seq + append + project
    sob o mesmo lock. Elimina TOCTOU entre leitura e write.
    """
    path = ensure_event_store(root)
    runner_id = (
        hooks.resolve_runner().get("runner_id")
        if hooks is not None and hooks.resolve_runner is not None
        else None
    )
    lock_path = _acquire_store_lock(
        path, timeout=timeout, retry_interval=0.05, lock_max_age=lock_max_age, runner_id=runner_id
    )
    try:
        tx_state = _load_tx_state_for_append(root, hooks)
        events: list[dict[str, Any]] = tx_state["events"]
        current_run: dict[str, Any] = tx_state["current_run"]
        _check_tx_preconditions(events, current_run, expected_first_seq, expected_projection_hash)

        new_events = _prepare_events_for_append(events, build_events_fn(events), hooks=hooks)
        if not new_events:
            return {
                "last_event_seq": current_run["last_event_seq"],
                "projection_hash_sha256": current_run["projection_hash_sha256"],
                "events_appended": 0,
            }

        if (
            tx_state.get("using_snapshot")
            and hooks is not None
            and hooks.reload_tx_state is not None
            and any(e["action"].startswith(("actor.", "verification.")) for e in new_events)
        ):
            tx_state = hooks.reload_tx_state(root, hooks)
            events = tx_state["events"]

        final_events = events + new_events
        if hooks is not None and hooks.validate_identity_history is not None:
            hooks.validate_identity_history(root, final_events)
        projected_views = (
            hooks.project_tx_views(tx_state, final_events, new_events)
            if hooks is not None and hooks.project_tx_views is not None
            else None
        )
        if hooks is not None and hooks.prepare_activation is not None:
            hooks.prepare_activation(root, events, final_events)

        serialized_lines = [
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in new_events
        ]
        _write_serialized_lines(path, serialized_lines)
        return _persist_tx_result(
            root, projected_views, final_events, new_events, after_append, result_task_id, hooks
        )
    finally:
        _release_store_lock(lock_path)
