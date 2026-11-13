from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bootstrap import bootstrap_workspace
from .errors import ESAAError
from .plugins import (
    activate_roadmap,
    deactivate_roadmap,
    diagnose_plugin,
    install_plugin,
    list_available_plugins,
    list_installed_plugins,
    list_roadmaps,
    plugin_status,
    remove_plugin,
    scaffold_plugin,
    set_roadmap_status,
    update_plugin,
    validate_plugin,
)
from .queries import list_activity, list_tasks
from .reject_codes import INPUT_INVALID
from .runner_inputs import register_commands_input, show_commands_input, validate_commands_input
from .scenarios import run_hotfix_trace
from .service import ESAAService
from .snapshot import compact_event_store, create_snapshot
from .status import status_command
from .store_runtime import init_hash_chain, parse_event_store, verify_hash_chain
from .vocabulary import vocabulary_payload


@dataclass(frozen=True)
class CliContext:
    """Execution context passed to every CLI subcommand handler."""

    root: Path
    service: ESAAService
    args: Any


HandlerFn = Callable[[CliContext], dict[str, Any] | int]


def cli_resource_limits(args: Any) -> dict[str, int] | None:
    values = {
        "max_bytes_per_update": getattr(args, "max_file_bytes", None),
        "max_bytes_total": getattr(args, "max_total_bytes", None),
        "max_file_updates": getattr(args, "max_file_updates", None),
    }
    return {key: value for key, value in values.items() if value is not None} or None


def read_json_arg(path_arg: str) -> object:
    try:
        raw = sys.stdin.read() if path_arg == "-" else Path(path_arg).read_text(encoding="utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise ESAAError(INPUT_INVALID, f"input {path_arg!r}: {exc}", penalizes_counter=False) from exc


def read_authorization(path_arg: str | None) -> dict[str, Any] | None:
    path = (path_arg or os.environ.get("ESAA_AUTHORIZATION") or "").strip()
    if not path:
        return None
    payload = read_json_arg(path)
    if not isinstance(payload, dict):
        raise ESAAError("ACTOR_AUTH_FAILED", "authorization must be a JSON object")
    return payload


def read_file_updates(path_arg: str) -> list[dict[str, str]]:
    payload = read_json_arg(path_arg)
    if not isinstance(payload, list):
        raise ESAAError("SCHEMA_INVALID", "--file-updates must be a JSON array")
    for item in payload:
        if (
            not isinstance(item, dict)
            or "path" not in item
            or not any(k in item for k in ("content", "edits", "binary"))
        ):
            raise ESAAError(
                "SCHEMA_INVALID", "--file-updates items require path and one of content, edits, or binary"
            )
    return payload


def _require_authorization(args: Any, message: str) -> dict[str, Any]:
    authorization = read_authorization(getattr(args, "authorization", None))
    if authorization is None:
        raise ESAAError("ACTOR_AUTH_FAILED", message)
    return authorization


def _interactive_onboard_answers() -> dict[str, Any]:
    display_name = input("Como os agentes devem te chamar? ").strip()
    return {
        "operator_name": display_name,
        "workflow_preferences": {"guided_onboarding": True},
    }


def _handle_bootstrap(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return bootstrap_workspace(
        ctx.root,
        profile=args.profile,
        force=args.force,
        preserve_guides=args.preserve_guides,
        merge_guides=args.merge_guides,
    )


def _handle_init(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    result = ctx.service.init(
        run_id=args.run_id,
        master_correlation_id=args.master_correlation_id,
        force=args.force,
        with_demo_tasks=args.with_demo_tasks,
    )
    if args.with_chain:
        result["chain"] = init_hash_chain(ctx.root)
    return result


def _handle_run(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    steps = None if args.until_done else args.steps
    return ctx.service.run(steps=steps, dry_run=args.dry_run, parallel=args.parallel)


def _handle_submit(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    agent_output = read_json_arg(args.file)
    if not isinstance(agent_output, dict):
        raise ESAAError("SCHEMA_INVALID", "submit payload must be a JSON object")
    return ctx.service.submit(
        agent_output,
        actor=args.actor,
        dry_run=args.dry_run,
        authorization=read_authorization(getattr(args, "authorization", None)),
    )


def _handle_claim(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.claim_task(
        args.task_id,
        actor=args.actor,
        notes=args.notes,
        notify_transition=args.notify_transition,
        dry_run=args.dry_run,
        authorization=read_authorization(getattr(args, "authorization", None)),
    )


def _handle_complete(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    file_updates = read_file_updates(args.file_updates) if args.file_updates else None
    return ctx.service.complete_task(
        args.task_id,
        actor=args.actor,
        checks=args.checks,
        execution_id=args.execution_id,
        notes=args.notes,
        file_updates=file_updates,
        issue_id=args.issue_id,
        fixes=args.fixes,
        notify_transition=args.notify_transition,
        dry_run=args.dry_run,
        authorization=read_authorization(getattr(args, "authorization", None)),
    )


def _handle_review(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.review_task(
        args.task_id,
        actor=args.actor,
        decision=args.decision,
        tasks=args.tasks,
        review_mode=args.review_mode,
        notify_completion=args.notify_completion,
        notify_transition=args.notify_transition,
        dry_run=args.dry_run,
        authorization=read_authorization(getattr(args, "authorization", None)),
    )


def _handle_actor_bootstrap(ctx: CliContext) -> dict[str, Any]:
    auth = _require_authorization(ctx.args, "actor bootstrap requires --authorization")
    return ctx.service.bootstrap_actor_authority(auth, dry_run=ctx.args.dry_run)


def _handle_actor_register(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    auth = _require_authorization(args, "actor register requires --authorization")
    return ctx.service.register_actor(
        actor_id=args.actor_id,
        role=args.role,
        authorization_scope=args.authorization_scope,
        actor_public_key_hex=args.actor_public_key_hex,
        authorization=auth,
        dry_run=args.dry_run,
    )


def _handle_actor_bind_alias(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    auth = _require_authorization(args, "actor bind-alias requires --authorization")
    return ctx.service.bind_actor_alias(
        actor_id=args.actor_id,
        alias_id=args.alias_id,
        authorization=auth,
        dry_run=args.dry_run,
    )


def _handle_actor_trust_import(ctx: CliContext) -> dict[str, Any]:
    pin = read_json_arg(ctx.args.pin)
    if not isinstance(pin, dict):
        raise ESAAError("INVALID_ARGUMENT", "trust pin must be a JSON object")
    return ctx.service.import_owner_trust_pin(pin)


def _handle_reject(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.reject_output(
        args.task_id,
        error_code=args.error_code,
        source_action=args.source_action,
        message=args.message,
        dry_run=args.dry_run,
    )


def _handle_onboard(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    if args.answers:
        answers = read_json_arg(args.answers)
        if not isinstance(answers, dict):
            raise ESAAError("PROJECT_PROFILE_INVALID", "onboard answers must be a JSON object")
    else:
        answers = _interactive_onboard_answers()
    return ctx.service.onboard(answers, dry_run=args.dry_run)


def _handle_verification_run(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.verification_run(
        args.task_id, read_json_arg(args.candidate), actor=args.actor, dry_run=args.dry_run
    )


def _handle_task_list(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return list_tasks(
        ctx.root,
        statuses=args.statuses,
        kind=args.kind,
        assigned_to=args.assigned_to,
        source=args.source,
        limit=args.limit,
        cursor=args.cursor,
    )


def _handle_activity_list(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return list_activity(
        ctx.root,
        task_id=args.task_id,
        actions=args.actions,
        exclude_actions=args.exclude_actions,
        hide_verify=args.hide_verify,
        after_seq=args.after_seq,
        limit=args.limit,
    )


def _handle_task_create(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.create_task(
        args.task_id,
        task_kind=args.kind,
        title=args.title,
        resource_limits=cli_resource_limits(args),
        description=args.description,
        outputs=args.outputs,
        depends_on=args.depends_on,
        targets=args.targets,
        boundary_grant=args.boundary_grant,
        task_type=args.task_type,
        acceptance_criteria=args.acceptance_criteria,
        required_review_mode=args.required_review_mode,
        supersedes=args.supersedes,
        executable_checks=args.executable_checks,
        dry_run=args.dry_run,
    )


def _handle_task_amend(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.amend_task(
        args.task_id,
        description=args.description,
        title=args.title,
        acceptance_criteria=args.acceptance_criteria,
        task_kind=args.task_kind,
        task_type=args.task_type,
        depends_on=args.depends_on,
        outputs=args.outputs,
        required_review_mode=args.required_review_mode,
        required_verification=args.required_verification,
        boundary_grant=args.boundary_grant,
        executable_checks=args.executable_checks,
        clear_boundary_grants=args.clear_boundary_grants,
        scope_patch=args.scope_patch,
        resource_limits=cli_resource_limits(args),
        dry_run=args.dry_run,
    )


def _handle_task_set_limits(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    limits = cli_resource_limits(args)
    if limits is None:
        raise ESAAError("INVALID_ARGUMENT", "task set-limits requires at least one limit option")
    return ctx.service.set_task_limits(
        args.task_id,
        limits,
        reason=args.reason,
        authorized_by=args.authorized_by,
        dry_run=args.dry_run,
    )


def _handle_contract_migrate(ctx: CliContext) -> dict[str, Any]:
    from .contract_migrate import migrate_active_contracts

    return migrate_active_contracts(ctx.root, dry_run=ctx.args.dry_run, emit_events=True)


def _handle_contract_revert(ctx: CliContext) -> dict[str, Any]:
    from .contract_migrate import revert_active_contracts

    return revert_active_contracts(ctx.root, ctx.args.backup_dir, dry_run=ctx.args.dry_run, emit_events=True)


def _handle_contract_set(ctx: CliContext) -> dict[str, Any]:
    from .contract_migrate import record_contract_set

    return record_contract_set(ctx.root, ctx.args.contracts, dry_run=ctx.args.dry_run)


def _handle_issue_report(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.report_issue(
        args.task_id,
        actor=args.actor,
        issue_id=args.issue_id,
        severity=args.severity,
        title=args.title,
        symptom=args.symptom,
        repro_steps=args.repro_steps,
        fixes=args.fixes,
        dry_run=args.dry_run,
    )


def _handle_hotfix_create(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    return ctx.service.create_hotfix(
        issue_id=args.issue_id,
        fixes=args.fixes,
        executable_checks=args.executable_checks,
        scope_patch=args.scope_patch,
        boundary_grant=args.boundary_grant,
        outputs=args.outputs,
        dry_run=args.dry_run,
    )


def _handle_project(ctx: CliContext) -> dict[str, Any]:
    from .projector import write_lock_projections

    result = ctx.service.project()
    locks_written = write_lock_projections(ctx.root, parse_event_store(ctx.root))
    if locks_written:
        result.update(locks_written)
    return result


def _handle_verify(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    if getattr(args, "chain", False):
        result = verify_hash_chain(ctx.root)
    elif getattr(args, "full", False):
        result = ctx.service.verify_full()
    else:
        result = ctx.service.verify()
    if result.get("verify_status") == "ok" and (ctx.root / ".roadmap" / "activity.jsonl").exists():
        from .contract_migrate import check_contract_drift

        drift = check_contract_drift(ctx.root)
        if drift["contract_status"] != "unrecorded":
            result["contract_status"] = drift["contract_status"]
            if drift["divergent_contracts"]:
                result["divergent_contracts"] = drift["divergent_contracts"]
    return result


def _handle_store_repair(ctx: CliContext) -> dict[str, Any]:
    from .store_repair import repair_event_store

    return repair_event_store(ctx.root, dry_run=ctx.args.dry_run)


def _handle_input_binary(ctx: CliContext) -> dict[str, Any]:
    from .binary_input import stage_task_input

    args = ctx.args
    return stage_task_input(ctx.service, args.task_id, args.actor, args.source, args.size, args.sha256)


def _handle_plugin_list(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    if args.bundled and args.external:
        raise ESAAError("INVALID_ARGUMENT", "--bundled and --external are mutually exclusive")
    source_filter = "bundled" if args.bundled else ("external" if args.external else None)
    return {
        "plugins": (
            list_available_plugins(ctx.root, source_filter=source_filter)
            if args.available
            else list_installed_plugins(ctx.root)
        )
    }


def _handle_runner_metrics(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    if args.file:
        payload = read_json_arg(args.file)
        if not isinstance(payload, dict):
            raise ESAAError("SCHEMA_INVALID", "runner metrics file must contain a JSON object")
    else:
        payload = {
            "task_id": args.task_id,
            "actor": args.actor,
            "runner_id": args.runner_id,
            "runner_kind": args.runner_kind,
            "model": args.model,
            "command_surface": args.command_surface,
            "started_at": args.started_at,
            "ended_at": args.ended_at,
            "latency_ms": args.latency_ms,
            "input_tokens": args.input_tokens,
            "output_tokens": args.output_tokens,
            "total_tokens": args.total_tokens,
            "cost_estimate": args.cost_estimate,
            "status": args.status,
            "error_code": args.error_code,
            "correlation_id": args.correlation_id,
        }
    return ctx.service.record_runner_metrics(payload, dry_run=args.dry_run)


def _handle_snapshot(ctx: CliContext) -> dict[str, Any]:
    args = ctx.args
    if args.compact:
        return compact_event_store(ctx.root, before=args.before, dry_run=args.dry_run)
    return create_snapshot(ctx.root, before=args.before, dry_run=args.dry_run)


CLI_HANDLERS: dict[tuple[str, ...], HandlerFn] = {
    ("bootstrap",): _handle_bootstrap,
    ("init",): _handle_init,
    ("run",): _handle_run,
    ("submit",): _handle_submit,
    ("claim",): _handle_claim,
    ("complete",): _handle_complete,
    ("review",): _handle_review,
    ("actor", "bootstrap"): _handle_actor_bootstrap,
    ("actor", "register"): _handle_actor_register,
    ("actor", "bind-alias"): _handle_actor_bind_alias,
    ("actor", "trust-import"): _handle_actor_trust_import,
    ("actor", "show"): lambda ctx: ctx.service.show_actor_registry(),
    ("state",): lambda ctx: ctx.service.task_state(ctx.args.task_id),
    ("dispatch-context",): lambda ctx: ctx.service.dispatch_context(ctx.args.task_id),
    ("reject",): _handle_reject,
    ("onboard",): _handle_onboard,
    ("profile", "show"): lambda ctx: ctx.service.show_project_profile(),
    ("verification", "enable"): lambda ctx: ctx.service.verification_enable(
        read_json_arg(ctx.args.config), dry_run=ctx.args.dry_run
    ),
    ("verification", "run"): _handle_verification_run,
    ("verification", "result"): lambda ctx: ctx.service.verification_result(ctx.args.run_id),
    ("verification", "show"): lambda ctx: ctx.service.verification_show(),
    ("task", "list"): _handle_task_list,
    ("task", "release"): lambda ctx: ctx.service.release_task(
        ctx.args.task_id, reason=ctx.args.reason, dry_run=ctx.args.dry_run
    ),
    ("task", "create"): _handle_task_create,
    ("task", "amend"): _handle_task_amend,
    ("task", "set-limits"): _handle_task_set_limits,
    ("activity", "list"): _handle_activity_list,
    ("activity", "clear"): lambda ctx: ctx.service.clear_activity(
        force=ctx.args.force, dry_run=ctx.args.dry_run, backup_dir=ctx.args.backup_dir
    ),
    ("contract", "migrate"): _handle_contract_migrate,
    ("contract", "revert"): _handle_contract_revert,
    ("contract", "set"): _handle_contract_set,
    ("issue", "report"): _handle_issue_report,
    ("issue", "resolve"): lambda ctx: ctx.service.resolve_issue(
        ctx.args.issue_id, hotfix_task_id=ctx.args.hotfix_task_id, dry_run=ctx.args.dry_run
    ),
    ("hotfix", "create"): _handle_hotfix_create,
    ("process",): lambda ctx: ctx.service.process(dry_run=ctx.args.dry_run),
    ("project",): _handle_project,
    ("verify",): _handle_verify,
    ("chain", "init"): lambda ctx: init_hash_chain(ctx.root, force=ctx.args.force),
    ("chain", "verify"): lambda ctx: verify_hash_chain(ctx.root),
    ("store", "repair"): _handle_store_repair,
    ("status",): lambda ctx: status_command(ctx.root, ctx.args.format),
    ("eligible",): lambda ctx: ctx.service.eligible(),
    ("metrics",): lambda ctx: ctx.service.metrics(),
    ("input", "binary"): _handle_input_binary,
    ("input", "commands", "validate"): lambda ctx: validate_commands_input(Path(ctx.args.path)),
    ("input", "commands", "register"): lambda ctx: register_commands_input(
        ctx.root, Path(ctx.args.path), runner_id=ctx.args.runner_id
    ),
    ("input", "commands", "show"): lambda ctx: show_commands_input(ctx.root, runner_id=ctx.args.runner_id),
    ("plugin", "list"): _handle_plugin_list,
    ("plugin", "new"): lambda ctx: scaffold_plugin(
        ctx.root, ctx.args.plugin_id, directory=ctx.args.directory
    ),
    ("plugin", "validate"): lambda ctx: validate_plugin(ctx.root, ctx.args.plugin_ref),
    ("plugin", "doctor"): lambda ctx: diagnose_plugin(ctx.root, ctx.args.plugin_ref),
    ("plugin", "install"): lambda ctx: install_plugin(
        ctx.root, ctx.args.plugin_ref, dry_run=ctx.args.dry_run
    ),
    ("plugin", "update"): lambda ctx: update_plugin(ctx.root, ctx.args.plugin_ref, dry_run=ctx.args.dry_run),
    ("plugin", "remove"): lambda ctx: remove_plugin(ctx.root, ctx.args.plugin_id, dry_run=ctx.args.dry_run),
    ("plugin", "status"): lambda ctx: plugin_status(
        ctx.root, detail=ctx.args.detail, plugin_filter=ctx.args.plugin
    ),
    ("plugin-status",): lambda ctx: plugin_status(
        ctx.root, detail=ctx.args.detail, plugin_filter=ctx.args.plugin
    ),
    ("roadmap", "list"): lambda ctx: {"roadmaps": list_roadmaps(ctx.root, detail=ctx.args.detail)},
    ("roadmap", "status"): lambda ctx: {"roadmaps": list_roadmaps(ctx.root, detail=ctx.args.detail)},
    ("roadmap", "activate"): lambda ctx: activate_roadmap(
        ctx.root,
        ctx.args.plugin_id,
        execution_id=ctx.args.execution_id,
        input_path=ctx.args.input_path,
        dry_run=ctx.args.dry_run,
    ),
    ("roadmap", "pause"): lambda ctx: set_roadmap_status(
        ctx.root, ctx.args.plugin_id, ctx.args.execution_id, "paused", dry_run=ctx.args.dry_run
    ),
    ("roadmap", "resume"): lambda ctx: set_roadmap_status(
        ctx.root, ctx.args.plugin_id, ctx.args.execution_id, "active", dry_run=ctx.args.dry_run
    ),
    ("roadmap", "deactivate"): lambda ctx: deactivate_roadmap(
        ctx.root, ctx.args.plugin_id, ctx.args.execution_id, dry_run=ctx.args.dry_run
    ),
    ("effects", "recover"): lambda ctx: ctx.service.recover_file_effects(dry_run=ctx.args.dry_run),
    ("runner", "metrics"): _handle_runner_metrics,
    ("scenario", "hotfix"): lambda ctx: run_hotfix_trace(
        ctx.root, target_root=ctx.root if ctx.args.current else None, issue_id=ctx.args.issue_id
    ),
    ("lesson", "list"): lambda ctx: ctx.service.list_lessons(status=ctx.args.status),
    ("lesson", "approve"): lambda ctx: ctx.service.decide_lesson(
        ctx.args.lesson_id, "approve", reason=ctx.args.reason, dry_run=ctx.args.dry_run
    ),
    ("lesson", "reject"): lambda ctx: ctx.service.decide_lesson(
        ctx.args.lesson_id, "reject", reason=ctx.args.reason, dry_run=ctx.args.dry_run
    ),
    ("vocabulary",): lambda ctx: vocabulary_payload(profile=ctx.args.profile),
    ("snapshot",): _handle_snapshot,
    ("replay",): lambda ctx: ctx.service.replay(until=ctx.args.until, write_views=not ctx.args.no_write),
}


_SUBCOMMAND_ATTRS = (
    "actor_command",
    "profile_command",
    "verification_command",
    "task_command",
    "activity_command",
    "contract_command",
    "issue_command",
    "hotfix_command",
    "chain_command",
    "store_command",
    "input_command",
    "commands_command",
    "plugin_command",
    "roadmap_command",
    "effects_command",
    "runner_command",
    "scenario_command",
    "lesson_command",
)


def command_path(args: Any) -> tuple[str, ...]:
    parts: list[str] = [str(args.command)]
    for attr in _SUBCOMMAND_ATTRS:
        val = getattr(args, attr, None)
        if val is not None:
            parts.append(str(val))
    return tuple(parts)


def dispatch_cli(ctx: CliContext) -> dict[str, Any] | int:
    path = command_path(ctx.args)
    handler = CLI_HANDLERS.get(path)
    if handler is None:
        raise ESAAError("UNKNOWN_COMMAND", f"unknown command: {' '.join(path)}")
    return handler(ctx)
