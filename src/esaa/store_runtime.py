from __future__ import annotations

from pathlib import Path
from typing import Any

from .compat import normalize_legacy_event
from .constants import SCHEMA_VERSION
from .event_schema import validate_event_for_append
from .events import make_event
from .identity_history import validate_identity_history, validate_identity_representation
from .project_profile import project_profile_view
from .projector import apply_events, finalize_views, projection_summary, replay_state
from .provenance import resolve_runner, validate_runner_block
from .store import (
    JSONL_REPAIR_HINT,
    StoreHooks,
    _acquire_store_lock,
    _release_store_lock,
    compute_event_hash,
    ensure_event_store,
    load_agent_contract,
    load_agent_result_schema,
    load_project_profile,
    load_roadmap,
    next_event_seq,
    record_concurrency_metric,
    require_task,
    save_issues,
    save_lessons,
    save_project_profile,
    save_roadmap,
    scan_event_offsets,
    snapshot_concurrency_metrics,
)
from .store import (
    append_events as _store_append_events,
)
from .store import (
    append_transactional as _store_append_transactional,
)
from .store import (
    init_hash_chain as _store_init_hash_chain,
)
from .store import (
    parse_event_store as _store_parse_event_store,
)
from .store import (
    parse_event_store_tail as _store_parse_event_store_tail,
)
from .store import (
    parse_event_store_text as _store_parse_event_store_text,
)
from .store import (
    read_event_at_offset as _store_read_event_at_offset,
)
from .store import (
    verify_hash_chain as _store_verify_hash_chain,
)
from .trust_root import advance_checkpoint, prepare_activation


def _load_tx_state(root: Path, hooks: StoreHooks | None) -> dict[str, Any]:
    from .snapshot import load_verified_replay

    replay = load_verified_replay(root)
    using_snapshot = (
        replay.used_snapshot
        and not replay.has_actor_events
        and not replay.has_verification_events
        and not any(e["action"].startswith(("actor.", "verification.")) for e in replay.tail_events)
    )
    events = _store_parse_event_store(root, hooks=hooks or DEFAULT_STORE_HOOKS)
    state = replay.state if using_snapshot else replay_state(events)
    return {
        "events": events,
        "state": state,
        "using_snapshot": using_snapshot,
        "replay": replay,
        "current_run": projection_summary(state),
    }


def _reload_tx_state(root: Path, hooks: StoreHooks | None) -> dict[str, Any]:
    events = _store_parse_event_store(root, hooks=hooks or DEFAULT_STORE_HOOKS)
    state = replay_state(events)
    return {
        "events": events,
        "state": state,
        "using_snapshot": False,
        "replay": None,
        "current_run": projection_summary(state),
    }


def _project_tx_views(
    tx_state: dict[str, Any],
    final_events: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    state = tx_state["state"]
    final_roadmap, final_issues, final_lessons = finalize_views(apply_events(state, new_events), copy=False)
    if tx_state.get("using_snapshot"):
        replay = tx_state["replay"]
        profile_events = [
            e for e in (replay.tail_events + new_events) if e["action"] == "project.profile.set"
        ]
        final_project_profile = (
            project_profile_view(profile_events) if profile_events else replay.project_profile
        )
    else:
        final_project_profile = project_profile_view(final_events)
    return final_roadmap, final_issues, final_lessons, final_project_profile


def _normalize_event_fast(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") == SCHEMA_VERSION and "payload" in raw:
        return raw
    return normalize_legacy_event(raw)


DEFAULT_STORE_HOOKS = StoreHooks(
    normalize_event=_normalize_event_fast,
    validate_runner=validate_runner_block,
    validate_representation=validate_identity_representation,
    validate_identity_history=validate_identity_history,
    validate_append_event=validate_event_for_append,
    prepare_activation=prepare_activation,
    advance_checkpoint=advance_checkpoint,
    event_factory=make_event,
    resolve_runner=resolve_runner,
    load_tx_state=_load_tx_state,
    reload_tx_state=_reload_tx_state,
    project_tx_views=_project_tx_views,
)


def parse_event_store(root: Path, *, hooks: StoreHooks | None = None) -> list[dict[str, Any]]:
    return _store_parse_event_store(root, hooks=hooks or DEFAULT_STORE_HOOKS)


def parse_event_store_text(
    root: Path,
    text: str,
    *,
    cache_key: str | None = None,
    hooks: StoreHooks | None = None,
) -> list[dict[str, Any]]:
    return _store_parse_event_store_text(root, text, cache_key=cache_key, hooks=hooks or DEFAULT_STORE_HOOKS)


def parse_event_store_tail(
    root: Path,
    offset_bytes: int,
    *,
    expected_first_seq: int,
    expected_prev_hash: str | None = None,
    hooks: StoreHooks | None = None,
) -> list[dict[str, Any]]:
    return _store_parse_event_store_tail(
        root,
        offset_bytes,
        expected_first_seq=expected_first_seq,
        expected_prev_hash=expected_prev_hash,
        hooks=hooks or DEFAULT_STORE_HOOKS,
    )


def read_event_at_offset(
    root: Path, offset_bytes: int, *, hooks: StoreHooks | None = None
) -> tuple[dict[str, Any], int]:
    return _store_read_event_at_offset(root, offset_bytes, hooks=hooks or DEFAULT_STORE_HOOKS)


def append_events(
    root: Path,
    events: list[dict[str, Any]],
    lock_timeout: float = 10.0,
    retry_interval: float = 0.05,
    lock_max_age: float = 120.0,
    *,
    hooks: StoreHooks | None = None,
) -> None:
    _store_append_events(
        root,
        events,
        lock_timeout=lock_timeout,
        retry_interval=retry_interval,
        lock_max_age=lock_max_age,
        hooks=hooks or DEFAULT_STORE_HOOKS,
    )


def append_transactional(
    root: Path,
    build_events_fn: Any,
    expected_first_seq: int | None = None,
    expected_projection_hash: str | None = None,
    timeout: float = 30.0,
    lock_max_age: float = 120.0,
    after_append: Any = None,
    result_task_id: str | None = None,
    *,
    hooks: StoreHooks | None = None,
) -> dict[str, Any]:
    return _store_append_transactional(
        root,
        build_events_fn,
        expected_first_seq=expected_first_seq,
        expected_projection_hash=expected_projection_hash,
        timeout=timeout,
        lock_max_age=lock_max_age,
        after_append=after_append,
        result_task_id=result_task_id,
        hooks=hooks or DEFAULT_STORE_HOOKS,
    )


def init_hash_chain(root: Path, force: bool = False, *, hooks: StoreHooks | None = None) -> dict[str, Any]:
    return _store_init_hash_chain(root, force=force, hooks=hooks or DEFAULT_STORE_HOOKS)


def verify_hash_chain(root: Path, *, hooks: StoreHooks | None = None) -> dict[str, Any]:
    return _store_verify_hash_chain(root, hooks=hooks or DEFAULT_STORE_HOOKS)


__all__ = [
    "DEFAULT_STORE_HOOKS",
    "JSONL_REPAIR_HINT",
    "StoreHooks",
    "_acquire_store_lock",
    "_release_store_lock",
    "append_events",
    "append_transactional",
    "compute_event_hash",
    "ensure_event_store",
    "init_hash_chain",
    "load_agent_contract",
    "load_agent_result_schema",
    "load_project_profile",
    "load_roadmap",
    "next_event_seq",
    "parse_event_store",
    "parse_event_store_tail",
    "parse_event_store_text",
    "read_event_at_offset",
    "record_concurrency_metric",
    "require_task",
    "save_issues",
    "save_lessons",
    "save_project_profile",
    "save_roadmap",
    "scan_event_offsets",
    "snapshot_concurrency_metrics",
    "verify_hash_chain",
]
