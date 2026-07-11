from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .adapters.http_llm import HttpLlmAdapter
from .bootstrap import bootstrap_workspace
from .constants import ESAA_VERSION, PACKAGE_VERSION, SCHEMA_VERSION
from .errors import ESAAError
from .plugins import (
    activate_roadmap,
    deactivate_roadmap,
    diagnose_plugin,
    install_plugin,
    list_available_plugins,
    list_installed_plugins,
    list_roadmaps,
    remove_plugin,
    scaffold_plugin,
    set_roadmap_status,
    validate_plugin,
)
from .provenance import ENV_RUNNER_ID
from .runner_inputs import register_commands_input, show_commands_input, validate_commands_input
from .scenarios import run_hotfix_trace
from .service import ESAAService
from .snapshot import compact_event_store, create_snapshot
from .store import init_hash_chain, verify_hash_chain
from .vocabulary import vocabulary_payload


def _read_json_arg(path_arg: str) -> object:
    raw = sys.stdin.read() if path_arg == "-" else Path(path_arg).read_text(encoding="utf-8")
    return json.loads(raw)


def _read_file_updates(path_arg: str) -> list[dict[str, str]]:
    payload = _read_json_arg(path_arg)
    if not isinstance(payload, list):
        raise ESAAError("SCHEMA_INVALID", "--file-updates must be a JSON array")
    for item in payload:
        if not isinstance(item, dict) or "path" not in item or "content" not in item:
            raise ESAAError("SCHEMA_INVALID", "--file-updates items require path and content")
    return payload


def _interactive_onboard_answers(root: Path) -> dict[str, Any]:
    display_name = input("Como os agentes devem te chamar? ").strip()
    return {
        "operator_name": display_name,
        "workflow_preferences": {"guided_onboarding": True},
    }


def _plugin_status(root: Path, detail: bool = False, plugin_filter: str | None = None) -> dict:
    """Cross-reference planned tasks (per-plugin) with projected state."""
    roadmap_dir = root / ".roadmap"
    if not roadmap_dir.is_dir():
        raise ESAAError("ROADMAP_DIR_MISSING", f".roadmap not found under {root}")

    projection_path = roadmap_dir / "roadmap.json"
    projected_status: dict[str, str] = {}
    if projection_path.is_file():
        try:
            proj = json.loads(projection_path.read_text(encoding="utf-8"))
            for t in proj.get("tasks", []):
                tid = t.get("task_id")
                if tid:
                    projected_status[tid] = t.get("status", "?")
        except (ValueError, OSError) as exc:
            raise ESAAError("PROJECTION_UNREADABLE", str(exc)) from exc

    plugins: list[dict] = []
    grand_totals: dict[str, int] = {}

    for path in sorted(roadmap_dir.glob("roadmap*.json")):
        if path.name == "roadmap.schema.json" or path.name.endswith(".template.json"):
            continue
        if plugin_filter and path.name != plugin_filter:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        tasks = data.get("tasks") or []
        if not tasks:
            continue

        by_planned_status: dict[str, int] = {}
        by_live_status: dict[str, int] = {}
        in_projection = 0
        items: list[dict] = []

        for t in tasks:
            tid = t.get("task_id", "?")
            planned = t.get("status", "todo")
            live = projected_status.get(tid)
            by_planned_status[planned] = by_planned_status.get(planned, 0) + 1
            effective = live if live is not None else planned
            by_live_status[effective] = by_live_status.get(effective, 0) + 1
            grand_totals[effective] = grand_totals.get(effective, 0) + 1
            if live is not None:
                in_projection += 1
            if detail:
                items.append(
                    {
                        "task_id": tid,
                        "title": t.get("title", ""),
                        "kind": t.get("task_kind"),
                        "planned_status": planned,
                        "live_status": live,
                    }
                )

        plugins.append(
            {
                "plugin_file": str(path.relative_to(root)).replace("\\", "/"),
                "tasks_declared": len(tasks),
                "in_projection": in_projection,
                "by_live_status": by_live_status,
                "by_planned_status": by_planned_status,
                **({"tasks": items} if detail else {}),
            }
        )

    return {
        "root": str(root),
        "projection_present": projection_path.is_file(),
        "plugins": plugins,
        "grand_totals_by_live_status": grand_totals,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="esaa", description="ESAA deterministic orchestrator core")
    parser.add_argument("--root", default=".", help="project root path")
    parser.add_argument(
        "--runner",
        default=None,
        help="runner identity stamped on every event (G08); overrides ESAA_RUNNER_ID",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PACKAGE_VERSION} (protocol {SCHEMA_VERSION}, esaa {ESAA_VERSION})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    cmd_bootstrap = sub.add_parser("bootstrap", help="install packaged ESAA governance templates")
    cmd_bootstrap.add_argument("--profile", choices=["public", "production"], default="public")
    cmd_bootstrap.add_argument("--force", action="store_true")
    bootstrap_guide_mode = cmd_bootstrap.add_mutually_exclusive_group()
    bootstrap_guide_mode.add_argument("--preserve-guides", action="store_true")
    bootstrap_guide_mode.add_argument("--merge-guides", action="store_true")

    cmd_init = sub.add_parser("init", help="initialize canonical clean-state (empty tasks by default)")
    cmd_init.add_argument("--run-id", default="RUN-0001")
    cmd_init.add_argument("--master-correlation-id", default="CID-ESAA-INIT")
    cmd_init.add_argument("--force", action="store_true")
    cmd_init.add_argument(
        "--with-demo-tasks",
        action="store_true",
        help="seed demo tasks T-1000/T-1010/T-1020 (ignored when a plugin roadmap supplies tasks)",
    )

    cmd_run = sub.add_parser("run", help="execute orchestration steps (mock adapter)")
    cmd_run.add_argument("--steps", type=int, default=1)
    cmd_run.add_argument(
        "--parallel", type=int, default=1, help="number of independent tasks to dispatch per wave"
    )
    cmd_run.add_argument("--adapter", choices=["mock", "http"], default="mock")
    cmd_run.add_argument("--llm-url", default=None, help="HTTP adapter endpoint (or ESAA_LLM_URL)")
    cmd_run.add_argument("--llm-token", default=None, help="HTTP adapter bearer token")
    cmd_run.add_argument("--llm-timeout", type=float, default=30.0)
    cmd_run.add_argument(
        "--until-done",
        action="store_true",
        help="run autonomously until no eligible task remains (ignores --steps)",
    )
    cmd_run.add_argument("--dry-run", action="store_true")

    cmd_submit = sub.add_parser("submit", help="validate and apply an agent.result JSON")
    cmd_submit.add_argument(
        "file", nargs="?", default="-", help="path to agent.result JSON file (default: stdin)"
    )
    cmd_submit.add_argument("--actor", required=True, help="agent identity (e.g. agent-spec, claude-code)")
    cmd_submit.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_claim = sub.add_parser("claim", help="append a deterministic claim transition")
    cmd_claim.add_argument("task_id")
    cmd_claim.add_argument("--actor", required=True)
    cmd_claim.add_argument("--notes", default=None)
    cmd_claim.add_argument("--notify-transition", action="store_true", help="speak the resulting task transition message")
    cmd_claim.add_argument("--dry-run", action="store_true")

    cmd_complete = sub.add_parser("complete", help="append a deterministic complete transition")
    cmd_complete.add_argument("task_id")
    cmd_complete.add_argument("--actor", required=True)
    cmd_complete.add_argument("--notes", default=None)
    cmd_complete.add_argument("--check", action="append", dest="checks", required=True)
    cmd_complete.add_argument("--file-updates", default=None, help="JSON array file, or '-' for stdin")
    cmd_complete.add_argument("--issue-id", default=None)
    cmd_complete.add_argument("--fixes", default=None)
    cmd_complete.add_argument("--notify-transition", action="store_true", help="speak the resulting task transition message")
    cmd_complete.add_argument("--dry-run", action="store_true")

    cmd_review = sub.add_parser("review", help="append a deterministic review transition")
    cmd_review.add_argument("task_id")
    cmd_review.add_argument("--actor", required=True)
    cmd_review.add_argument("--decision", choices=["approve", "request_changes"], required=True)
    cmd_review.add_argument(
        "--review-mode",
        choices=["functional", "security", "regression", "docs", "governance", "release"],
        default=None,
        help="G07 optional typed review mode",
    )
    cmd_review.add_argument("--task", action="append", dest="tasks", default=None)
    cmd_review.add_argument(
        "--notify-completion",
        action="store_true",
        help="speak 'Task done' when review approve moves the task to done",
    )
    cmd_review.add_argument("--notify-transition", action="store_true", help="speak the resulting task transition message")
    cmd_review.add_argument("--dry-run", action="store_true")

    cmd_state = sub.add_parser("state", help="show deterministic task state and expected action")
    cmd_state.add_argument("task_id")

    cmd_dispatch = sub.add_parser("dispatch-context", help="show the minimal harness context for one task")
    cmd_dispatch.add_argument("task_id")

    cmd_reject = sub.add_parser("reject", help="append an orchestrator output.rejected event")
    cmd_reject.add_argument("task_id")
    cmd_reject.add_argument("--error-code", required=True)
    cmd_reject.add_argument("--source-action", required=True)
    cmd_reject.add_argument("--message", required=True)
    cmd_reject.add_argument("--dry-run", action="store_true")

    cmd_onboard = sub.add_parser("onboard", help="guided project onboarding and profile creation")
    cmd_onboard.add_argument("--answers", default=None, help="JSON answers file for non-interactive onboarding")
    cmd_onboard.add_argument("--dry-run", action="store_true", help="preview profile/tasks without appending events")

    cmd_profile = sub.add_parser("profile", help="project profile commands")
    profile_sub = cmd_profile.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser("show", help="show projected project profile")

    cmd_task = sub.add_parser("task", help="deterministic task commands")
    task_sub = cmd_task.add_subparsers(dest="task_command", required=True)
    cmd_task_create = task_sub.add_parser("create", help="append an orchestrator task.create event")
    cmd_task_create.add_argument("task_id")
    cmd_task_create.add_argument("--kind", choices=["spec", "impl", "qa"], required=True)
    cmd_task_create.add_argument("--title", required=True)
    cmd_task_create.add_argument("--description", default=None)
    cmd_task_create.add_argument("--output", action="append", dest="outputs", default=None)
    cmd_task_create.add_argument("--depends-on", action="append", dest="depends_on", default=None)
    cmd_task_create.add_argument("--target", action="append", dest="targets", default=None)
    cmd_task_create.add_argument(
        "--task-type",
        choices=["feature", "hotfix", "audit", "release", "memory", "governance", "maintenance"],
        default=None,
        help="G07 optional operational intent for the task",
    )
    cmd_task_create.add_argument(
        "--acceptance-criterion",
        action="append",
        dest="acceptance_criteria",
        default=None,
        help="G07 ordered acceptance criterion; repeat to add multiple AC items",
    )
    cmd_task_create.add_argument(
        "--required-review-mode",
        choices=["functional", "security", "regression", "docs", "governance", "release"],
        default=None,
        help="G07 optional single required review mode",
    )
    cmd_task_create.add_argument(
        "--supersedes",
        action="append",
        dest="supersedes",
        default=None,
        help="G07 existing task id superseded by this task; repeat for multiple ids",
    )
    cmd_task_create.add_argument(
        "--boundary-grant",
        action="append",
        dest="boundary_grant",
        default=None,
        help="extra fnmatch write pattern granted to this task only (operator authority; T-2070)",
    )
    cmd_task_create.add_argument("--dry-run", action="store_true")
    cmd_task_amend = task_sub.add_parser("amend", help="amend metadata of a todo task")
    cmd_task_amend.add_argument("task_id")
    cmd_task_amend.add_argument("--description", default=None)
    cmd_task_amend.add_argument("--title", default=None)
    cmd_task_amend.add_argument("--kind", dest="task_kind", choices=["spec", "impl", "qa"], default=None)
    cmd_task_amend.add_argument(
        "--task-type",
        dest="task_type",
        choices=["feature", "hotfix", "audit", "release", "memory", "governance", "maintenance"],
        default=None,
    )
    cmd_task_amend.add_argument("--depends-on", action="append", dest="depends_on", default=None)
    cmd_task_amend.add_argument("--output", action="append", dest="outputs", default=None)
    cmd_task_amend.add_argument(
        "--acceptance-criterion",
        action="append",
        dest="acceptance_criteria",
        default=None,
        help="replace acceptance criteria; repeat to add multiple AC items",
    )
    cmd_task_amend.add_argument(
        "--required-review-mode",
        dest="required_review_mode",
        choices=["functional", "security", "regression", "docs", "governance", "release"],
        default=None,
    )
    cmd_task_amend.add_argument(
        "--required-verification",
        action="append",
        dest="required_verification",
        default=None,
        help="replace required verification items; repeat to add multiple",
    )
    cmd_task_amend.add_argument("--dry-run", action="store_true")

    cmd_issue = sub.add_parser("issue", help="deterministic issue commands")
    issue_sub = cmd_issue.add_subparsers(dest="issue_command", required=True)

    cmd_issue_report = issue_sub.add_parser("report", help="append an issue.report through the agent gate")
    cmd_issue_report.add_argument("task_id")
    cmd_issue_report.add_argument("--actor", required=True)
    cmd_issue_report.add_argument("--issue-id", required=True)
    cmd_issue_report.add_argument("--severity", choices=["low", "medium", "high", "critical"], required=True)
    cmd_issue_report.add_argument("--title", required=True)
    cmd_issue_report.add_argument("--symptom", required=True)
    cmd_issue_report.add_argument("--repro-step", action="append", dest="repro_steps", required=True)
    cmd_issue_report.add_argument("--fixes", default=None)
    cmd_issue_report.add_argument("--dry-run", action="store_true")

    cmd_issue_resolve = issue_sub.add_parser("resolve", help="append an orchestrator issue.resolve event")
    cmd_issue_resolve.add_argument("--issue-id", required=True)
    cmd_issue_resolve.add_argument("--hotfix-task-id", default=None)
    cmd_issue_resolve.add_argument("--dry-run", action="store_true")

    cmd_hotfix = sub.add_parser("hotfix", help="deterministic hotfix commands")
    hotfix_sub = cmd_hotfix.add_subparsers(dest="hotfix_command", required=True)
    cmd_hotfix_create = hotfix_sub.add_parser("create", help="append an orchestrator hotfix.create event")
    cmd_hotfix_create.add_argument("--issue-id", required=True)
    cmd_hotfix_create.add_argument("--fixes", required=True)
    cmd_hotfix_create.add_argument("--scope-patch", action="append", dest="scope_patch", default=None)
    cmd_hotfix_create.add_argument("--dry-run", action="store_true")

    cmd_activity = sub.add_parser("activity", help="activity.jsonl administrative commands")
    activity_sub = cmd_activity.add_subparsers(dest="activity_command", required=True)
    cmd_activity_clear = activity_sub.add_parser("clear", help="backup and clear .roadmap/activity.jsonl")
    cmd_activity_clear.add_argument(
        "--force", action="store_true", help="required to truncate activity.jsonl"
    )
    cmd_activity_clear.add_argument("--dry-run", action="store_true", help="report what would be cleared")
    cmd_activity_clear.add_argument(
        "--backup-dir", default=".roadmap/backups", help="backup directory before clearing"
    )

    cmd_process = sub.add_parser("process", help="process all pending files from .roadmap/inbox/")
    cmd_process.add_argument(
        "--dry-run", action="store_true", help="validate without persisting or moving files"
    )

    sub.add_parser("project", help="reproject read-models from event store")
    cmd_verify = sub.add_parser("verify", help="verify projection consistency")
    cmd_verify.add_argument("--chain", action="store_true", help="verify event-store hash chain")
    cmd_chain = sub.add_parser("chain", help="event-store hash chain commands")
    chain_sub = cmd_chain.add_subparsers(dest="chain_command", required=True)
    cmd_chain_init = chain_sub.add_parser("init", help="append a chain.anchor event")
    cmd_chain_init.add_argument("--force", action="store_true")
    sub.add_parser("eligible", help="list eligible tasks and parallel groups")
    sub.add_parser("metrics", help="emit structured runtime metrics")

    cmd_input = sub.add_parser("input", help="local runner input commands")
    input_sub = cmd_input.add_subparsers(dest="input_command", required=True)
    cmd_input_commands = input_sub.add_parser("commands", help="runner command capability input")
    input_commands_sub = cmd_input_commands.add_subparsers(dest="commands_command", required=True)
    cmd_input_commands_validate = input_commands_sub.add_parser(
        "validate", help="validate a command capability YAML file"
    )
    cmd_input_commands_validate.add_argument("path")
    cmd_input_commands_register = input_commands_sub.add_parser(
        "register", help="register a command capability YAML file for this runner"
    )
    cmd_input_commands_register.add_argument("path")
    cmd_input_commands_register.add_argument("--runner-id", default=None)
    cmd_input_commands_show = input_commands_sub.add_parser("show", help="show registered commands input")
    cmd_input_commands_show.add_argument("--runner-id", default=None)

    cmd_plugin = sub.add_parser("plugin", help="installable plugin commands")
    plugin_sub = cmd_plugin.add_subparsers(dest="plugin_command", required=True)
    cmd_plugin_list = plugin_sub.add_parser("list", help="list installed or available plugins")
    cmd_plugin_list.add_argument("--available", action="store_true")
    cmd_plugin_list.add_argument(
        "--bundled", action="store_true", help="when listing available plugins, show bundled only"
    )
    cmd_plugin_list.add_argument(
        "--external", action="store_true", help="when listing available plugins, show external catalog only"
    )
    cmd_plugin_new = plugin_sub.add_parser("new", help="scaffold a plugin directory package")
    cmd_plugin_new.add_argument("plugin_id")
    cmd_plugin_new.add_argument("--directory", default=None)
    cmd_plugin_validate = plugin_sub.add_parser("validate", help="validate an available plugin")
    cmd_plugin_validate.add_argument("plugin_ref")
    cmd_plugin_doctor = plugin_sub.add_parser("doctor", help="diagnose a plugin package")
    cmd_plugin_doctor.add_argument("plugin_ref")
    cmd_plugin_install = plugin_sub.add_parser("install", help="install a plugin into this workspace")
    cmd_plugin_install.add_argument("plugin_ref")
    cmd_plugin_remove = plugin_sub.add_parser("remove", help="remove an installed plugin from this workspace")
    cmd_plugin_remove.add_argument("plugin_id")
    cmd_plugin_status = plugin_sub.add_parser("status", help="show roadmap execution status for plugins")
    cmd_plugin_status.add_argument("--detail", action="store_true")

    cmd_roadmap = sub.add_parser("roadmap", help="plugin roadmap execution commands")
    roadmap_sub = cmd_roadmap.add_subparsers(dest="roadmap_command", required=True)
    cmd_roadmap_list = roadmap_sub.add_parser("list", help="list roadmap executions")
    cmd_roadmap_list.add_argument("--detail", action="store_true")
    cmd_roadmap_status = roadmap_sub.add_parser("status", help="show roadmap execution status")
    cmd_roadmap_status.add_argument("--detail", action="store_true")
    cmd_roadmap_activate = roadmap_sub.add_parser("activate", help="activate a plugin roadmap")
    cmd_roadmap_activate.add_argument("plugin_id")
    cmd_roadmap_activate.add_argument("--execution-id", default="default")
    cmd_roadmap_activate.add_argument("--input", dest="input_path", default=None)
    for name, help_text in (
        ("pause", "pause a roadmap execution"),
        ("resume", "resume a roadmap execution"),
        ("deactivate", "deactivate a roadmap execution"),
    ):
        cmd = roadmap_sub.add_parser(name, help=help_text)
        cmd.add_argument("plugin_id")
        cmd.add_argument("--execution-id", default="default")

    cmd_plugin_status = sub.add_parser(
        "plugin-status",
        help="show planned-vs-projected status per roadmap plugin",
    )
    cmd_plugin_status.add_argument(
        "--detail",
        action="store_true",
        help="include per-task list (task_id, title, projected status)",
    )
    cmd_plugin_status.add_argument(
        "--plugin",
        default=None,
        help="filter to one plugin filename (e.g. roadmap.sso-client.json)",
    )

    cmd_effects = sub.add_parser("effects", help="file effect recovery commands")
    effects_sub = cmd_effects.add_subparsers(dest="effects_command", required=True)
    cmd_effects_recover = effects_sub.add_parser(
        "recover", help="reapply missing file effects from artifacts"
    )
    cmd_effects_recover.add_argument("--dry-run", action="store_true")

    cmd_runner = sub.add_parser("runner", help="external runner telemetry commands")
    runner_sub = cmd_runner.add_subparsers(dest="runner_command", required=True)
    cmd_runner_metrics = runner_sub.add_parser("metrics", help="record external runner metrics")
    cmd_runner_metrics.add_argument("--file", default=None, help="JSON payload file, or '-' for stdin")
    cmd_runner_metrics.add_argument("--task-id", default=None)
    cmd_runner_metrics.add_argument("--actor", default=None)
    cmd_runner_metrics.add_argument("--runner-id", default=None)
    cmd_runner_metrics.add_argument("--runner-kind", default=None)
    cmd_runner_metrics.add_argument("--model", default=None)
    cmd_runner_metrics.add_argument("--command-surface", default=None)
    cmd_runner_metrics.add_argument("--started-at", default=None)
    cmd_runner_metrics.add_argument("--ended-at", default=None)
    cmd_runner_metrics.add_argument("--latency-ms", type=int, default=None)
    cmd_runner_metrics.add_argument("--input-tokens", type=int, default=None)
    cmd_runner_metrics.add_argument("--output-tokens", type=int, default=None)
    cmd_runner_metrics.add_argument("--total-tokens", type=int, default=None)
    cmd_runner_metrics.add_argument("--cost-estimate", type=float, default=None)
    cmd_runner_metrics.add_argument("--status", default=None)
    cmd_runner_metrics.add_argument("--error-code", default=None)
    cmd_runner_metrics.add_argument("--correlation-id", default=None)
    cmd_runner_metrics.add_argument("--dry-run", action="store_true")

    cmd_scenario = sub.add_parser("scenario", help="deterministic operational scenarios")
    scenario_sub = cmd_scenario.add_subparsers(dest="scenario_command", required=True)
    cmd_scenario_hotfix = scenario_sub.add_parser("hotfix", help="run the demonstrable hotfix trace")
    cmd_scenario_hotfix.add_argument("--current", action="store_true", help="run in the current workspace")
    cmd_scenario_hotfix.add_argument("--issue-id", default="ISS-HOTFIX-TRACE")

    cmd_vocabulary = sub.add_parser("vocabulary", help="show protocol vocabulary mappings")
    cmd_vocabulary.add_argument("--profile", default=None)

    cmd_snapshot = sub.add_parser("snapshot", help="write a projection checkpoint")
    cmd_snapshot.add_argument("--before", type=int, required=True, help="include events with event_seq <= N")
    cmd_snapshot.add_argument(
        "--compact", action="store_true", help="also archive included events beside the snapshot"
    )
    cmd_snapshot.add_argument(
        "--dry-run", action="store_true", help="show snapshot/compaction plan without writing"
    )

    cmd_replay = sub.add_parser("replay", help="rebuild state until event id/seq")
    cmd_replay.add_argument("--until", default=None, help="event_seq (number) or event_id")
    cmd_replay.add_argument("--no-write", action="store_true", help="compute replay without writing views")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if getattr(args, "runner", None):
        os.environ[ENV_RUNNER_ID] = args.runner  # G08: precedencia CLI > env > default
    root = Path(args.root).resolve()
    adapter = None
    if getattr(args, "command", None) == "run" and getattr(args, "adapter", "mock") == "http":
        url = args.llm_url
        if url:
            adapter = HttpLlmAdapter(url=url, token=args.llm_token, timeout=args.llm_timeout)
        else:
            adapter = HttpLlmAdapter.from_env()
    service = ESAAService(root=root, adapter=adapter)

    try:
        if args.command == "bootstrap":
            result = bootstrap_workspace(
                root,
                profile=args.profile,
                force=args.force,
                preserve_guides=args.preserve_guides,
                merge_guides=args.merge_guides,
            )
        elif args.command == "init":
            result = service.init(
                run_id=args.run_id,
                master_correlation_id=args.master_correlation_id,
                force=args.force,
                with_demo_tasks=args.with_demo_tasks,
            )
        elif args.command == "run":
            steps = None if args.until_done else args.steps
            result = service.run(steps=steps, dry_run=args.dry_run, parallel=args.parallel)
        elif args.command == "submit":
            agent_output = _read_json_arg(args.file)
            if not isinstance(agent_output, dict):
                raise ESAAError("SCHEMA_INVALID", "submit payload must be a JSON object")
            result = service.submit(agent_output, actor=args.actor, dry_run=args.dry_run)
        elif args.command == "claim":
            result = service.claim_task(
                args.task_id,
                actor=args.actor,
                notes=args.notes,
                notify_transition=args.notify_transition,
                dry_run=args.dry_run,
            )
        elif args.command == "complete":
            file_updates = _read_file_updates(args.file_updates) if args.file_updates else None
            result = service.complete_task(
                args.task_id,
                actor=args.actor,
                checks=args.checks,
                notes=args.notes,
                file_updates=file_updates,
                issue_id=args.issue_id,
                fixes=args.fixes,
                notify_transition=args.notify_transition,
                dry_run=args.dry_run,
            )
        elif args.command == "review":
            result = service.review_task(
                args.task_id,
                actor=args.actor,
                decision=args.decision,
                tasks=args.tasks,
                review_mode=args.review_mode,
                notify_completion=args.notify_completion,
                notify_transition=args.notify_transition,
                dry_run=args.dry_run,
            )
        elif args.command == "state":
            result = service.task_state(args.task_id)
        elif args.command == "dispatch-context":
            result = service.dispatch_context(args.task_id)
        elif args.command == "reject":
            result = service.reject_output(
                args.task_id,
                error_code=args.error_code,
                source_action=args.source_action,
                message=args.message,
                dry_run=args.dry_run,
            )
        elif args.command == "onboard":
            if args.answers:
                answers = _read_json_arg(args.answers)
                if not isinstance(answers, dict):
                    raise ESAAError("PROJECT_PROFILE_INVALID", "onboard answers must be a JSON object")
            else:
                answers = _interactive_onboard_answers(root)
            result = service.onboard(answers, dry_run=args.dry_run)
        elif args.command == "profile" and args.profile_command == "show":
            result = service.show_project_profile()
        elif args.command == "task" and args.task_command == "create":
            result = service.create_task(
                args.task_id,
                task_kind=args.kind,
                title=args.title,
                description=args.description,
                outputs=args.outputs,
                depends_on=args.depends_on,
                targets=args.targets,
                boundary_grant=args.boundary_grant,
                task_type=args.task_type,
                acceptance_criteria=args.acceptance_criteria,
                required_review_mode=args.required_review_mode,
                supersedes=args.supersedes,
                dry_run=args.dry_run,
            )
        elif args.command == "task" and args.task_command == "amend":
            result = service.amend_task(
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
                dry_run=args.dry_run,
            )
        elif args.command == "issue" and args.issue_command == "report":
            result = service.report_issue(
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
        elif args.command == "issue" and args.issue_command == "resolve":
            result = service.resolve_issue(
                args.issue_id,
                hotfix_task_id=args.hotfix_task_id,
                dry_run=args.dry_run,
            )
        elif args.command == "hotfix" and args.hotfix_command == "create":
            result = service.create_hotfix(
                issue_id=args.issue_id,
                fixes=args.fixes,
                scope_patch=args.scope_patch,
                dry_run=args.dry_run,
            )
        elif args.command == "activity" and args.activity_command == "clear":
            result = service.clear_activity(
                force=args.force,
                dry_run=args.dry_run,
                backup_dir=args.backup_dir,
            )
        elif args.command == "process":
            result = service.process(dry_run=args.dry_run)
        elif args.command == "project":
            result = service.project()
        elif args.command == "verify":
            result = verify_hash_chain(root) if getattr(args, "chain", False) else service.verify()
        elif args.command == "chain" and args.chain_command == "init":
            result = init_hash_chain(root, force=args.force)
        elif args.command == "eligible":
            result = service.eligible()
        elif args.command == "metrics":
            result = service.metrics()
        elif args.command == "input" and args.input_command == "commands":
            if args.commands_command == "validate":
                result = validate_commands_input(Path(args.path))
            elif args.commands_command == "register":
                result = register_commands_input(root, Path(args.path), runner_id=args.runner_id)
            elif args.commands_command == "show":
                result = show_commands_input(root, runner_id=args.runner_id)
            else:
                raise ESAAError("UNKNOWN_COMMAND", f"unknown input commands action: {args.commands_command}")
        elif args.command == "plugin" and args.plugin_command == "list":
            source_filter = None
            if args.bundled and args.external:
                raise ESAAError("INVALID_ARGUMENT", "--bundled and --external are mutually exclusive")
            if args.bundled:
                source_filter = "bundled"
            if args.external:
                source_filter = "external"
            result = {
                "plugins": (
                    list_available_plugins(root, source_filter=source_filter)
                    if args.available
                    else list_installed_plugins(root)
                ),
            }
        elif args.command == "plugin" and args.plugin_command == "new":
            result = scaffold_plugin(root, args.plugin_id, directory=args.directory)
        elif args.command == "plugin" and args.plugin_command == "validate":
            result = validate_plugin(root, args.plugin_ref)
        elif args.command == "plugin" and args.plugin_command == "doctor":
            result = diagnose_plugin(root, args.plugin_ref)
        elif args.command == "plugin" and args.plugin_command == "install":
            result = install_plugin(root, args.plugin_ref)
        elif args.command == "plugin" and args.plugin_command == "remove":
            result = remove_plugin(root, args.plugin_id)
        elif args.command == "plugin" and args.plugin_command == "status":
            result = {"roadmaps": list_roadmaps(root, detail=args.detail)}
        elif args.command == "roadmap" and args.roadmap_command in {"list", "status"}:
            result = {"roadmaps": list_roadmaps(root, detail=args.detail)}
        elif args.command == "roadmap" and args.roadmap_command == "activate":
            result = activate_roadmap(
                root,
                args.plugin_id,
                execution_id=args.execution_id,
                input_path=args.input_path,
            )
        elif args.command == "roadmap" and args.roadmap_command == "pause":
            result = set_roadmap_status(root, args.plugin_id, args.execution_id, "paused")
        elif args.command == "roadmap" and args.roadmap_command == "resume":
            result = set_roadmap_status(root, args.plugin_id, args.execution_id, "active")
        elif args.command == "roadmap" and args.roadmap_command == "deactivate":
            result = deactivate_roadmap(root, args.plugin_id, args.execution_id)
        elif args.command == "plugin-status":
            result = _plugin_status(root, detail=args.detail, plugin_filter=args.plugin)
        elif args.command == "effects" and args.effects_command == "recover":
            result = service.recover_file_effects(dry_run=args.dry_run)
        elif args.command == "runner" and args.runner_command == "metrics":
            if args.file:
                payload = _read_json_arg(args.file)
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
            result = service.record_runner_metrics(payload, dry_run=args.dry_run)
        elif args.command == "scenario" and args.scenario_command == "hotfix":
            result = run_hotfix_trace(
                root, target_root=root if args.current else None, issue_id=args.issue_id
            )
        elif args.command == "vocabulary":
            result = vocabulary_payload(profile=args.profile)
        elif args.command == "snapshot":
            if args.compact:
                result = compact_event_store(root, before=args.before, dry_run=args.dry_run)
            else:
                result = create_snapshot(root, before=args.before, dry_run=args.dry_run)
        elif args.command == "replay":
            result = service.replay(until=args.until, write_views=not args.no_write)
        else:
            raise ESAAError("UNKNOWN_COMMAND", f"unknown command: {args.command}")

        print(json.dumps(result, ensure_ascii=True, indent=2))
        verify_status = result.get("verify_status")
        if verify_status in {"mismatch", "corrupted"}:
            return 2
        return 0
    except ESAAError as exc:
        # RF08: mensagem curta e padronizada para a proxima tentativa do LLM.
        msg = exc.message.splitlines()[0]
        if len(msg) > 200:
            msg = msg[:197] + "..."
        print(
            json.dumps(
                {"error_code": exc.code, "error_message": msg},
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
