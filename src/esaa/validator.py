from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from jsonschema import ValidationError, validate

from .boundary_paths import assert_writable_not_governed, path_within_scope
from .errors import ESAAError
from .external_effects import task_accepts_external_path
from .reject_codes import REVIEW_MODE_MISMATCH, REVIEW_MODE_REQUIRED
from .state_machine import REJECT_PRIOR_MISMATCH, allowed_actions_for
from .utils import normalize_rel_path


# RF08: mensagem curta - caminho + razao, sem stack/instance dump.
def _short_validation_error(exc: ValidationError) -> str:
    path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
    msg = exc.message.splitlines()[0]
    return f"{path}: {msg[:140]}"


# R8: minimo de verification.checks por task_kind (alinhado a AGENT_CONTRACT.verification_gate).
MIN_CHECKS_BY_KIND = {"spec": 1, "impl": 1, "qa": 1, "hotfix": 2}
G07_TASK_TYPES = {"feature", "hotfix", "audit", "release", "memory", "governance", "maintenance"}
G07_REVIEW_MODES = {"functional", "security", "regression", "docs", "governance", "release"}
DEFAULT_RESOURCE_LIMITS = {
    "max_file_updates": 32,
    "max_bytes_per_update": 2 * 1024 * 1024,
    "max_bytes_total": 8 * 1024 * 1024,
}


def _non_empty_strings(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise ESAAError("SCHEMA_INVALID", f"{field} must be a list")
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ESAAError("SCHEMA_INVALID", f"{field} items must be non-empty strings")
        out.append(value.strip())
    return out


def validate_g07_task_create_payload(payload: dict[str, Any], existing_task_ids: set[str]) -> None:
    task_id = str(payload.get("task_id", "")).strip()

    task_type = payload.get("task_type")
    if task_type is not None and task_type not in G07_TASK_TYPES:
        raise ESAAError("SCHEMA_INVALID", f"invalid task_type: {task_type}")

    acceptance_criteria = payload.get("acceptance_criteria")
    if acceptance_criteria is not None:
        _non_empty_strings(acceptance_criteria, "acceptance_criteria")

    required_review_mode = payload.get("required_review_mode")
    if required_review_mode is not None and required_review_mode not in G07_REVIEW_MODES:
        raise ESAAError("SCHEMA_INVALID", f"invalid required_review_mode: {required_review_mode}")

    supersedes = payload.get("supersedes")
    if supersedes is None:
        return

    supersedes_values = _non_empty_strings(supersedes, "supersedes")
    if len(set(supersedes_values)) != len(supersedes_values):
        raise ESAAError("SCHEMA_INVALID", "supersedes must not contain duplicate task ids")
    if task_id in supersedes_values:
        raise ESAAError("SCHEMA_INVALID", "supersedes must not reference the task itself")
    missing = sorted(set(supersedes_values) - existing_task_ids)
    if missing:
        raise ESAAError("TASK_NOT_FOUND", f"supersedes references unknown task ids: {missing}")


def validate_g07_review_mode(task: dict[str, Any], event: dict[str, Any]) -> None:
    review_mode = event.get("review_mode")
    if review_mode is not None and review_mode not in G07_REVIEW_MODES:
        raise ESAAError("SCHEMA_INVALID", f"invalid review_mode: {review_mode}")

    required_review_mode = task.get("required_review_mode")
    if not required_review_mode:
        return
    if review_mode is None:
        raise ESAAError(
            REVIEW_MODE_REQUIRED,
            f"task {task['task_id']} requires review_mode={required_review_mode}",
        )
    if review_mode != required_review_mode:
        raise ESAAError(
            REVIEW_MODE_MISMATCH,
            f"task {task['task_id']} requires review_mode={required_review_mode}, got {review_mode}",
        )


def _positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def resource_limits_from_policy(policy: dict[str, Any]) -> dict[str, int]:
    configured = (
        policy.get("resource_limits", {}) if isinstance(policy.get("resource_limits", {}), dict) else {}
    )
    return {
        "max_file_updates": _positive_int(
            configured.get("max_file_updates"), DEFAULT_RESOURCE_LIMITS["max_file_updates"]
        ),
        "max_bytes_per_update": _positive_int(
            configured.get("max_bytes_per_update"), DEFAULT_RESOURCE_LIMITS["max_bytes_per_update"]
        ),
        "max_bytes_total": _positive_int(
            configured.get("max_bytes_total"), DEFAULT_RESOURCE_LIMITS["max_bytes_total"]
        ),
    }


def _file_update_size(item: dict[str, Any]) -> int:
    """Mede o tamanho de um file_update para resource limits.

    Semantica dual: no fluxo governado os limites rodam APOS a resolucao de
    edits (AGENT_CONTRACT: resolve antes de external effects, resource limits,
    staging), entao este codigo mede o conteudo expandido - o branch de
    'edits' abaixo so e alcancado por chamadas standalone pre-resolucao e
    mede old_string+new_string como aproximacao.
    """
    if "content" in item:
        return len(str(item.get("content", "")).encode("utf-8"))
    if "edits" in item and isinstance(item.get("edits"), list):
        total = 0
        for edit in item["edits"]:
            if isinstance(edit, dict):
                total += len(str(edit.get("old_string", "")).encode("utf-8"))
                total += len(str(edit.get("new_string", "")).encode("utf-8"))
        return total
    return 0


def validate_file_update_resource_limits(file_updates: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    limits = resource_limits_from_policy(policy)
    if len(file_updates) > limits["max_file_updates"]:
        raise ESAAError(
            "RESOURCE_LIMIT_EXCEEDED",
            f"file_updates count {len(file_updates)} exceeds max_file_updates={limits['max_file_updates']}",
        )
    total = 0
    for item in file_updates:
        size = _file_update_size(item)
        if size > limits["max_bytes_per_update"]:
            raise ESAAError(
                "RESOURCE_LIMIT_EXCEEDED",
                f"file update {item.get('path')} has {size} bytes; max_bytes_per_update={limits['max_bytes_per_update']}",
            )
        total += size
    if total > limits["max_bytes_total"]:
        raise ESAAError(
            "RESOURCE_LIMIT_EXCEEDED",
            f"file_updates total {total} bytes exceeds max_bytes_total={limits['max_bytes_total']}",
        )


def validate_boundary_grant(patterns: list[str]) -> list[str]:
    """Valida padroes de boundary_grant na origem (T-2070).

    O grant e autoridade do operador gravada no event store; padroes que
    permitiriam traversal, runtime:// ou escrita na area de governanca sao
    rejeitados antes de qualquer evento ser emitido.
    """
    validated: list[str] = []
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            raise ESAAError("SCHEMA_INVALID", "boundary_grant pattern must not be empty")
        if pattern.startswith("runtime://"):
            raise ESAAError("SCHEMA_INVALID", f"boundary_grant cannot target runtime://: {pattern}")
        norm = normalize_rel_path(pattern)
        if norm.startswith("/") or (":" in PurePosixPath(norm).parts[0]):
            raise ESAAError("SCHEMA_INVALID", f"boundary_grant pattern must be relative: {pattern}")
        if any(part == ".." for part in PurePosixPath(norm).parts):
            raise ESAAError("SCHEMA_INVALID", f"boundary_grant pattern forbids traversal: {pattern}")
        if norm == ".roadmap" or norm.startswith(".roadmap/"):
            raise ESAAError("SCHEMA_INVALID", f"boundary_grant cannot target governance area: {pattern}")
        validated.append(norm)
    return validated


def validate_unique_file_update_paths(file_updates: list[dict[str, Any]]) -> None:
    """Rejeita paths normalizados duplicados em um unico output (ISS-T2042-DUP-FILE-UPDATES).

    Dois file_updates para o mesmo path significariam last-write-wins
    silencioso no staging; o Orchestrator rejeita antes de staging.
    """
    seen: set[str] = set()
    for item in file_updates:
        path = item["path"]
        if path in seen:
            raise ESAAError(
                "FILE_UPDATE_DUPLICATE_PATH",
                f"duplicate file_update path in a single output: {path}",
            )
        seen.add(path)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern.replace("\\", "/")) for pattern in patterns)


def _validate_safe_path(path: str) -> str:
    if path.startswith("runtime://"):
        return path
    norm = normalize_rel_path(path)
    if not norm or norm.startswith("/") or norm.startswith(".."):
        raise ESAAError("BOUNDARY_VIOLATION", f"invalid path: {path}")
    parts = PurePosixPath(norm).parts
    if any(part == ".." for part in parts):
        raise ESAAError("BOUNDARY_VIOLATION", f"path traversal forbidden: {path}")
    return norm


def validate_agent_output(
    output: dict[str, Any],
    schema: dict[str, Any],
    contract: dict[str, Any],
    task: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        validate(output, schema)
    except ValidationError as exc:
        raise ESAAError("SCHEMA_INVALID", _short_validation_error(exc)) from exc

    allowed_root = {"activity_event", "file_updates"}
    unknown_root = set(output.keys()) - allowed_root
    if unknown_root:
        raise ESAAError("SCHEMA_INVALID", f"unknown root keys: {sorted(unknown_root)}")

    event = output["activity_event"]
    action = event["action"]
    if action not in contract["vocabulary"]["allowed_agent_actions"]:
        raise ESAAError("UNKNOWN_ACTION", f"unknown action: {action}")

    # RF07: prior_status declarado deve bater com o status real do roadmap.
    if action != "issue.report":
        declared = event.get("prior_status")
        real = task["status"]
        if declared != real:
            raise ESAAError(REJECT_PRIOR_MISMATCH, f"declared={declared} real={real}")

    if action not in allowed_actions_for(task["status"]):
        raise ESAAError("WORKFLOW_GATE_VIOLATION", f"{action} not allowed in status={task['status']}")

    if event["task_id"] != task["task_id"]:
        raise ESAAError("SCHEMA_INVALID", "task_id mismatch")

    forbidden = set(contract["output_contract"]["activity_event"]["forbidden_fields"])
    found_forbidden = sorted([field for field in event.keys() if field in forbidden])
    if found_forbidden:
        raise ESAAError("SCHEMA_INVALID", f"forbidden fields: {found_forbidden}")

    if action == "complete":
        # R8: min de verification.checks por task_kind (hotfix=2).
        kind_key = "hotfix" if task.get("is_hotfix") else task["task_kind"]
        min_checks = MIN_CHECKS_BY_KIND.get(kind_key, 1)
        verification = event.get("verification", {})
        checks = verification.get("checks", [])
        if len(checks) < min_checks:
            raise ESAAError(
                "MISSING_VERIFICATION",
                f"complete requires >= {min_checks} verification checks for kind={kind_key}",
            )
        if task.get("is_hotfix"):
            if not event.get("issue_id") or not event.get("fixes"):
                raise ESAAError("MISSING_VERIFICATION", "hotfix complete requires issue_id and fixes")

    if action == "review":
        decision = event.get("decision")
        if decision not in {"approve", "request_changes"}:
            raise ESAAError("SCHEMA_INVALID", f"invalid review decision: {decision}")
        validate_g07_review_mode(task, event)

    updates = list(output.get("file_updates", []))
    _validate_boundaries(updates, contract, task)
    return event, updates


def _validate_boundaries(
    updates: list[dict[str, str]], contract: dict[str, Any], task: dict[str, Any]
) -> None:
    boundaries = contract["boundaries"]["by_task_kind"][task["task_kind"]]
    allowlist = boundaries["write"]
    denylist = boundaries.get("forbidden_write", [])

    scope_patch_enabled = contract["boundaries"]["patch_scope"]["enabled"]
    scope_patch = task.get("scope_patch", [])
    # T-2070: grant por tarefa concedido pelo operador via task.create.
    # Alternativa a allowlist do kind; nao se aplica a runtime:// e nunca
    # sobrepoe forbidden_write nem o safe-path.
    boundary_grant = [str(pattern) for pattern in task.get("boundary_grant", [])]

    for item in updates:
        path = _validate_safe_path(item["path"])
        if path.startswith("runtime://") and task_accepts_external_path(task, path):
            continue
        if (
            path.startswith("runtime://")
            and task.get("is_hotfix")
            and any(path_within_scope(path, str(prefix)) for prefix in scope_patch)
        ):
            continue
        if not _matches_any(path, allowlist) and not (
            boundary_grant and not path.startswith("runtime://") and _matches_any(path, boundary_grant)
        ):
            raise ESAAError("BOUNDARY_VIOLATION", f"path not allowed for {task['task_kind']}: {path}")
        if denylist and _matches_any(path, denylist):
            raise ESAAError("BOUNDARY_VIOLATION", f"path explicitly forbidden: {path}")

        if scope_patch_enabled and task.get("is_hotfix"):
            if not scope_patch:
                raise ESAAError("BOUNDARY_VIOLATION", "hotfix task missing scope_patch")
            if not any(path_within_scope(path, str(prefix)) for prefix in scope_patch):
                raise ESAAError("BOUNDARY_VIOLATION", f"path outside scope_patch: {path}")


def validate_resolved_file_boundaries(
    updates: list[dict[str, Any]], contract: dict[str, Any], task: dict[str, Any]
) -> None:
    boundaries = contract["boundaries"]["by_task_kind"][task["task_kind"]]
    denylist = boundaries.get("forbidden_write", [])

    for item in updates:
        target_path = item.get("_esaa_target_path")
        if not isinstance(target_path, str) or not target_path:
            continue
        assert_writable_not_governed(target_path)
        if denylist and _matches_any(target_path, denylist):
            raise ESAAError("BOUNDARY_VIOLATION", f"path explicitly forbidden: {target_path}")
