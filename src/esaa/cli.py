from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import yaml
from jsonschema.exceptions import SchemaError

from .adapters.http_llm import HttpLlmAdapter
from .cli_handlers import CliContext, command_path, dispatch_cli
from .constants import ESAA_VERSION, PACKAGE_VERSION, PROTOCOL_VERSION, SCHEMA_VERSION
from .errors import ESAAError
from .oplog import emit_oplog_entry, oplog_path_from_env
from .provenance import ENV_RUNNER_ID
from .queries import format_query
from .reject_codes import WORKSPACE_INVALID
from .service import ESAAService
from .store import reset_concurrency_metrics


def _format_cli_output(result: dict[str, Any], output_format: str) -> str:
    """Format CLI query results, preserving byte-identical JSON via format_query."""
    if output_format != "table" or "tasks" in result or "events" in result:
        return format_query(result, output_format)
    rows: list[dict[str, Any]] | None = None
    for value in result.values():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            rows = value
            break
    if rows is None:
        return format_query(result, output_format)
    if not rows:
        return "(empty)"
    columns = list(dict.fromkeys(key for row in rows for key in row.keys()))

    def _cell(val: Any) -> str:
        if isinstance(val, (list, dict)):
            raw = json.dumps(val, ensure_ascii=True)
        elif val is None:
            raw = ""
        else:
            raw = str(val)
        return "".join(c if c.isprintable() else " " for c in raw)

    return "\n".join(
        ["\t".join(columns)] + ["\t".join(_cell(row.get(col)) for col in columns) for row in rows]
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esaa",
        description="ESAA deterministic orchestrator core",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Agent workflow:
  Read AGENTS.md in the workspace selected by --root before making changes.
  Use eligible to discover tasks, then dispatch-context TASK-ID before work.
  Follow the returned contract, boundaries and active lessons.
  Use your real --runner identity for every command that writes events.
  Submit claim and complete separately; file_updates belongs only to complete.
  Let the Orchestrator apply effects; do not edit the event store or projections.
  Use 'esaa COMMAND --help' for command syntax.

Exit codes:
  0  Success
  1  Domain, input or environment error (JSON with error_code on stderr)
  2  Verification mismatch/corrupted, broken hash chain or failed verification run""",
    )
    parser.add_argument("--root", default=".", help="project root path")
    parser.add_argument(
        "--runner",
        default=None,
        help="runner identity stamped on every event (G08); overrides ESAA_RUNNER_ID",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PACKAGE_VERSION} (protocol {PROTOCOL_VERSION}, storage protocol {SCHEMA_VERSION}, esaa {ESAA_VERSION})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    cmd_bootstrap = sub.add_parser("bootstrap", help="install packaged ESAA governance templates")
    cmd_bootstrap.add_argument(
        "--profile",
        choices=["public", "production"],
        default="public",
        help="governance template profile to install (default: public)",
    )
    cmd_bootstrap.add_argument("--force", action="store_true", help="overwrite existing governance files")
    bootstrap_guide_mode = cmd_bootstrap.add_mutually_exclusive_group()
    bootstrap_guide_mode.add_argument(
        "--preserve-guides", action="store_true", help="keep existing guide files untouched"
    )
    bootstrap_guide_mode.add_argument(
        "--merge-guides", action="store_true", help="merge packaged guide sections into existing files"
    )

    cmd_init = sub.add_parser("init", help="initialize canonical clean-state (empty tasks by default)")
    cmd_init.add_argument("--run-id", default="RUN-0001", help="initial run identifier")
    cmd_init.add_argument(
        "--master-correlation-id", default="CID-ESAA-INIT", help="initial master correlation identifier"
    )
    cmd_init.add_argument("--force", action="store_true", help="reinitialize an existing event store")
    cmd_init.add_argument(
        "--with-chain",
        action="store_true",
        help="also anchor the event-store hash chain (opt-in; unanchored stays the default)",
    )
    cmd_init.add_argument(
        "--with-demo-tasks",
        action="store_true",
        help="seed demo tasks T-1000/T-1010/T-1020 (ignored when a plugin roadmap supplies tasks)",
    )

    cmd_run = sub.add_parser("run", help="[demo] execute orchestration steps (mock adapter)")
    cmd_run.add_argument("--steps", type=int, default=1, help="maximum orchestration steps to run")
    cmd_run.add_argument(
        "--parallel", type=int, default=1, help="number of independent tasks to dispatch per wave"
    )
    cmd_run.add_argument("--adapter", choices=["mock", "http"], default="mock", help="runner adapter backend")
    cmd_run.add_argument("--llm-url", default=None, help="HTTP adapter endpoint (or ESAA_LLM_URL)")
    cmd_run.add_argument("--llm-token", default=None, help="HTTP adapter bearer token")
    cmd_run.add_argument(
        "--llm-timeout", type=float, default=30.0, help="HTTP adapter request timeout in seconds"
    )
    cmd_run.add_argument(
        "--until-done",
        action="store_true",
        help="run autonomously until no eligible task remains (ignores --steps)",
    )
    cmd_run.add_argument("--dry-run", action="store_true", help="simulate without persisting events")

    cmd_submit = sub.add_parser("submit", help="validate and apply an agent.result JSON")
    cmd_submit.add_argument(
        "file", nargs="?", default="-", help="path to agent.result JSON file (default: stdin)"
    )
    cmd_submit.add_argument("--actor", required=True, help="agent identity (e.g. agent-spec, claude-code)")
    cmd_submit.add_argument(
        "--authorization",
        default=None,
        help="signed authorization JSON for privileged actions; or ESAA_AUTHORIZATION",
    )
    cmd_submit.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_claim = sub.add_parser("claim", help="append a deterministic claim transition")
    cmd_claim.add_argument("task_id", help="target task identifier")
    cmd_claim.add_argument("--actor", required=True, help="agent identity claiming the task")
    cmd_claim.add_argument("--notes", default=None, help="optional claim notes")
    cmd_claim.add_argument(
        "--notify-transition", action="store_true", help="[demo] speak the resulting task transition message"
    )
    cmd_claim.add_argument(
        "--authorization",
        default=None,
        help="signed authorization JSON for claim when identity is active; or ESAA_AUTHORIZATION",
    )
    cmd_claim.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_complete = sub.add_parser("complete", help="append a deterministic complete transition")
    cmd_complete.add_argument("task_id", help="target task identifier")
    cmd_complete.add_argument("--actor", required=True, help="agent identity completing the task")
    cmd_complete.add_argument("--notes", default=None, help="optional completion notes")
    cmd_complete.add_argument("--execution-id", default=None, help="optional verification execution id")
    cmd_complete.add_argument(
        "--check", action="append", dest="checks", required=True, help="verification check passed; repeatable"
    )
    cmd_complete.add_argument("--file-updates", default=None, help="JSON array file, or '-' for stdin")
    cmd_complete.add_argument("--issue-id", default=None, help="related issue identifier if applicable")
    cmd_complete.add_argument("--fixes", default=None, help="issue or task id fixed by this completion")
    cmd_complete.add_argument(
        "--notify-transition", action="store_true", help="[demo] speak the resulting task transition message"
    )
    cmd_complete.add_argument(
        "--authorization",
        default=None,
        help="signed authorization JSON for complete when identity is active; or ESAA_AUTHORIZATION",
    )
    cmd_complete.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_review = sub.add_parser("review", help="append a deterministic review transition")
    cmd_review.add_argument("task_id", help="target task identifier")
    cmd_review.add_argument("--actor", required=True, help="reviewer actor identity")
    cmd_review.add_argument(
        "--decision",
        choices=["approve", "request_changes"],
        required=True,
        help="review decision",
    )
    cmd_review.add_argument(
        "--review-mode",
        choices=["functional", "security", "regression", "docs", "governance", "release"],
        default=None,
        help="G07 optional typed review mode",
    )
    cmd_review.add_argument(
        "--task", action="append", dest="tasks", default=None, help="related task id; repeatable"
    )
    cmd_review.add_argument(
        "--notify-completion",
        action="store_true",
        help="[demo] speak 'Task done' when review approve moves the task to done",
    )
    cmd_review.add_argument(
        "--notify-transition", action="store_true", help="[demo] speak the resulting task transition message"
    )
    cmd_review.add_argument(
        "--authorization",
        default=None,
        help="signed authorization JSON for review; or ESAA_AUTHORIZATION",
    )
    cmd_review.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_actor = sub.add_parser("actor", help="authenticated actor registry commands")
    actor_sub = cmd_actor.add_subparsers(dest="actor_command", required=True)
    cmd_actor_bootstrap = actor_sub.add_parser(
        "bootstrap", help="activate the protected public bootstrap authority"
    )
    cmd_actor_bootstrap.add_argument(
        "--authorization",
        required=True,
        help="owner-signed authorization JSON (fixture keys in tests only)",
    )
    cmd_actor_bootstrap.add_argument("--dry-run", action="store_true", help="validate without persisting")
    cmd_actor_register = actor_sub.add_parser("register", help="register an actor through the Orchestrator")
    cmd_actor_register.add_argument("--actor-id", required=True, help="actor identifier to register")
    cmd_actor_register.add_argument(
        "--role",
        required=True,
        choices=["qa", "specification", "implementation"],
        help="actor role in governance",
    )
    cmd_actor_register.add_argument(
        "--scope",
        action="append",
        dest="authorization_scope",
        required=True,
        help="authorized scope; repeatable",
    )
    cmd_actor_register.add_argument(
        "--actor-public-key", required=True, dest="actor_public_key_hex", help="Ed25519 public key in hex"
    )
    cmd_actor_register.add_argument("--authorization", required=True, help="owner-signed authorization JSON")
    cmd_actor_register.add_argument("--dry-run", action="store_true", help="validate without persisting")
    cmd_actor_bind_alias = actor_sub.add_parser(
        "bind-alias",
        help="bind an explicit alias to a registered principal (owner-signed)",
    )
    cmd_actor_bind_alias.add_argument("--actor-id", required=True, help="registered principal actor id")
    cmd_actor_bind_alias.add_argument("--alias-id", required=True, help="alias identifier to bind")
    cmd_actor_bind_alias.add_argument(
        "--authorization", required=True, help="owner-signed authorization JSON"
    )
    cmd_actor_bind_alias.add_argument("--dry-run", action="store_true", help="validate without persisting")
    cmd_actor_trust_import = actor_sub.add_parser(
        "trust-import",
        help="import an owner trust pin into ESAA_TRUST_ROOT (never copies local anchor bytes)",
    )
    cmd_actor_trust_import.add_argument(
        "--pin",
        required=True,
        help="owner trust pin JSON path, or '-' for stdin",
    )
    actor_sub.add_parser("show", help="show the event-sourced actor registry")

    cmd_verification = sub.add_parser("verification", help="operator-configured executable verification")
    verification_sub = cmd_verification.add_subparsers(dest="verification_command", required=True)
    cmd_enable = verification_sub.add_parser(
        "enable", help="activate/update the operator check catalog and additive schemas"
    )
    cmd_enable.add_argument("--config", required=True, help="path to verification catalog JSON config")
    cmd_enable.add_argument("--dry-run", action="store_true", help="validate without persisting")
    verification_sub.add_parser("show", help="show the active catalog from events")
    cmd_vrun = verification_sub.add_parser("run", help="execute authorized checks on a candidate in Docker")
    cmd_vrun.add_argument("task_id", help="target task identifier")
    cmd_vrun.add_argument("--candidate", required=True, help="path to candidate payload JSON")
    cmd_vrun.add_argument("--actor", required=True, help="actor identity requesting verification")
    cmd_vrun.add_argument("--dry-run", action="store_true", help="preview plan without running Docker")
    cmd_vresult = verification_sub.add_parser("result", help="verify and inspect an execution result")
    cmd_vresult.add_argument("run_id", help="verification run identifier")
    cmd_state = sub.add_parser("state", help="show deterministic task state and expected action")
    cmd_state.add_argument("task_id", help="target task identifier")

    cmd_dispatch = sub.add_parser("dispatch-context", help="show the minimal harness context for one task")
    cmd_dispatch.add_argument("task_id", help="target task identifier")

    cmd_reject = sub.add_parser("reject", help="append an orchestrator output.rejected event")
    cmd_reject.add_argument("task_id", help="target task identifier")
    cmd_reject.add_argument("--error-code", required=True, help="rejection error code")
    cmd_reject.add_argument("--source-action", required=True, help="rejected action name")
    cmd_reject.add_argument("--message", required=True, help="human-readable rejection reason")
    cmd_reject.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_onboard = sub.add_parser("onboard", help="guided project onboarding and profile creation")
    cmd_onboard.add_argument(
        "--answers", default=None, help="JSON answers file for non-interactive onboarding"
    )
    cmd_onboard.add_argument(
        "--dry-run", action="store_true", help="preview profile/tasks without appending events"
    )

    cmd_profile = sub.add_parser("profile", help="project profile commands")
    profile_sub = cmd_profile.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser("show", help="show projected project profile")

    cmd_task = sub.add_parser("task", help="deterministic task commands")
    task_sub = cmd_task.add_subparsers(dest="task_command", required=True)
    cmd_task_list = task_sub.add_parser("list", help="list all tasks without writing state")
    cmd_task_list.add_argument(
        "--status",
        action="append",
        dest="statuses",
        choices=["todo", "in_progress", "review", "done"],
        help="filter by task status; repeatable",
    )
    cmd_task_list.add_argument("--kind", choices=["spec", "impl", "qa"], help="filter by task kind")
    cmd_task_list.add_argument("--assigned-to", help="filter by assigned actor")
    cmd_task_list.add_argument(
        "--source",
        choices=["event_store", "planned", "all"],
        default="all",
        help="filter by task source (default: all)",
    )
    cmd_task_list.add_argument("--limit", type=int, default=100, help="maximum tasks to return")
    cmd_task_list.add_argument("--cursor", help="pagination cursor from previous response")
    cmd_task_list.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="output format (default: json)",
    )
    cmd_release = task_sub.add_parser("release", help="release a stalled claim or reset blocked attempts")
    cmd_release.add_argument("task_id", help="target task identifier")
    cmd_release.add_argument("--reason", required=True, help="operator reason for releasing the claim")
    cmd_release.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_task_create = task_sub.add_parser("create", help="append an orchestrator task.create event")
    cmd_task_create.add_argument("task_id", help="unique task identifier")
    cmd_task_create.add_argument(
        "--kind", choices=["spec", "impl", "qa"], required=True, help="task governance kind"
    )
    cmd_task_create.add_argument("--title", required=True, help="short task title")
    cmd_task_create.add_argument("--max-file-bytes", type=int, help="maximum bytes per updated file")
    cmd_task_create.add_argument("--max-total-bytes", type=int, help="maximum total bytes across updates")
    cmd_task_create.add_argument("--max-file-updates", type=int, help="maximum file update entries")
    cmd_task_create.add_argument("--description", default=None, help="detailed task description")
    cmd_task_create.add_argument(
        "--output", action="append", dest="outputs", default=None, help="output file path; repeatable"
    )
    cmd_task_create.add_argument(
        "--depends-on",
        action="append",
        dest="depends_on",
        default=None,
        help="prerequisite task id; repeatable",
    )
    cmd_task_create.add_argument(
        "--target", action="append", dest="targets", default=None, help="target file path; repeatable"
    )
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
    cmd_task_create.add_argument(
        "--executable-check",
        action="append",
        dest="executable_checks",
        default=None,
        help="executable check id or command; repeatable",
    )
    cmd_task_create.add_argument("--dry-run", action="store_true", help="validate without persisting")
    cmd_task_amend = task_sub.add_parser("amend", help="amend metadata of a todo task")
    cmd_task_amend.add_argument("task_id", help="target todo task identifier")
    grant_group = cmd_task_amend.add_mutually_exclusive_group()
    grant_group.add_argument(
        "--boundary-grant",
        action="append",
        default=None,
        help="extra fnmatch write pattern to grant; repeatable",
    )
    grant_group.add_argument(
        "--clear-boundary-grants", action="store_true", help="remove all boundary grants from task"
    )
    cmd_task_amend.add_argument(
        "--scope-patch", action="append", default=None, help="scope patch entry; repeatable"
    )
    cmd_task_amend.add_argument("--description", default=None, help="replacement task description")
    cmd_task_amend.add_argument("--title", default=None, help="replacement task title")
    cmd_task_amend.add_argument(
        "--kind", dest="task_kind", choices=["spec", "impl", "qa"], default=None, help="replacement task kind"
    )
    cmd_task_amend.add_argument(
        "--task-type",
        dest="task_type",
        choices=["feature", "hotfix", "audit", "release", "memory", "governance", "maintenance"],
        default=None,
        help="replacement operational intent",
    )
    cmd_task_amend.add_argument(
        "--depends-on",
        action="append",
        dest="depends_on",
        default=None,
        help="replacement dependency task id; repeatable",
    )
    cmd_task_amend.add_argument(
        "--output",
        action="append",
        dest="outputs",
        default=None,
        help="replacement output file path; repeatable",
    )
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
        help="replacement required review mode",
    )
    cmd_task_amend.add_argument(
        "--required-verification",
        action="append",
        dest="required_verification",
        default=None,
        help="replace required verification items; repeat to add multiple",
    )
    cmd_task_amend.add_argument(
        "--executable-check",
        action="append",
        dest="executable_checks",
        default=None,
        help="replacement executable check; repeatable",
    )
    cmd_task_amend.add_argument("--max-file-bytes", type=int, help="maximum bytes per updated file")
    cmd_task_amend.add_argument("--max-total-bytes", type=int, help="maximum total bytes across updates")
    cmd_task_amend.add_argument("--max-file-updates", type=int, help="maximum file update entries")
    cmd_task_amend.add_argument("--dry-run", action="store_true", help="validate without persisting")
    cmd_task_set_limits = task_sub.add_parser(
        "set-limits", help="set resource limits of an in_progress task via an audited operator event"
    )
    cmd_task_set_limits.add_argument("task_id", help="target in_progress task identifier")
    cmd_task_set_limits.add_argument("--max-file-bytes", type=int, help="maximum bytes per updated file")
    cmd_task_set_limits.add_argument("--max-total-bytes", type=int, help="maximum total bytes across updates")
    cmd_task_set_limits.add_argument("--max-file-updates", type=int, help="maximum file update entries")
    cmd_task_set_limits.add_argument("--reason", required=True, help="operator reason for changing limits")
    cmd_task_set_limits.add_argument("--authorized-by", required=True, help="authorizing operator identity")
    cmd_task_set_limits.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_contract = sub.add_parser(
        "contract", help="migrate active governance schemas without bootstrap --force"
    )
    contract_sub = cmd_contract.add_subparsers(dest="contract_command", required=True)
    cmd_contract_migrate = contract_sub.add_parser(
        "migrate", help="selectively add binary file_updates and resource_limits to active schemas"
    )
    cmd_contract_migrate.add_argument(
        "--dry-run", action="store_true", help="preview without modifying files"
    )
    cmd_contract_revert = contract_sub.add_parser(
        "revert", help="restore migratable schemas from a contract migrate backup directory"
    )
    cmd_contract_revert.add_argument(
        "--from", dest="backup_dir", required=True, help="backup directory to restore from"
    )
    cmd_contract_revert.add_argument("--dry-run", action="store_true", help="preview without modifying files")
    cmd_contract_set = contract_sub.add_parser(
        "set", help="record active contract sha256 hashes into the event store (contract.set)"
    )
    cmd_contract_set.add_argument(
        "--contract",
        dest="contracts",
        action="append",
        default=None,
        help="contract filename under .roadmap/ to record (repeatable; defaults to all active contracts)",
    )
    cmd_contract_set.add_argument("--dry-run", action="store_true", help="preview without modifying files")

    cmd_issue = sub.add_parser("issue", help="deterministic issue commands")
    issue_sub = cmd_issue.add_subparsers(dest="issue_command", required=True)

    cmd_issue_report = issue_sub.add_parser("report", help="append an issue.report through the agent gate")
    cmd_issue_report.add_argument("task_id", help="task identifier associated with the issue")
    cmd_issue_report.add_argument("--actor", required=True, help="agent identity reporting the issue")
    cmd_issue_report.add_argument("--issue-id", required=True, help="unique issue identifier")
    cmd_issue_report.add_argument(
        "--severity",
        choices=["low", "medium", "high", "critical"],
        required=True,
        help="issue severity level",
    )
    cmd_issue_report.add_argument("--title", required=True, help="short issue title")
    cmd_issue_report.add_argument("--symptom", required=True, help="observed symptom description")
    cmd_issue_report.add_argument(
        "--repro-step",
        action="append",
        dest="repro_steps",
        required=True,
        help="reproduction step; repeatable",
    )
    cmd_issue_report.add_argument(
        "--fixes",
        default=None,
        help="also creates HF-<issue-id> with defaults; omit to use hotfix create with custom scope/grants",
    )
    cmd_issue_report.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_issue_resolve = issue_sub.add_parser("resolve", help="append an orchestrator issue.resolve event")
    cmd_issue_resolve.add_argument("--issue-id", required=True, help="issue identifier to resolve")
    cmd_issue_resolve.add_argument(
        "--hotfix-task-id", default=None, help="optional hotfix task id that resolved the issue"
    )
    cmd_issue_resolve.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_hotfix = sub.add_parser("hotfix", help="deterministic hotfix commands")
    hotfix_sub = cmd_hotfix.add_subparsers(dest="hotfix_command", required=True)
    cmd_hotfix_create = hotfix_sub.add_parser("create", help="append an orchestrator hotfix.create event")
    cmd_hotfix_create.add_argument("--issue-id", required=True, help="issue identifier being fixed")
    cmd_hotfix_create.add_argument("--fixes", required=True, help="task or defect identifier fixed")
    cmd_hotfix_create.add_argument(
        "--scope-patch", action="append", dest="scope_patch", default=None, help="scope patch; repeatable"
    )
    cmd_hotfix_create.add_argument(
        "--boundary-grant",
        action="append",
        default=None,
        help="extra fnmatch write pattern granted to this hotfix; repeatable",
    )
    cmd_hotfix_create.add_argument(
        "--output", action="append", dest="outputs", default=None, help="output file path; repeatable"
    )
    cmd_hotfix_create.add_argument(
        "--executable-check",
        action="append",
        dest="executable_checks",
        default=None,
        help="executable check id or command; repeatable",
    )
    cmd_hotfix_create.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_activity = sub.add_parser("activity", help="activity.jsonl administrative commands")
    activity_sub = cmd_activity.add_subparsers(dest="activity_command", required=True)
    cmd_activity_list = activity_sub.add_parser("list", help="read/filter events without changing the store")
    cmd_activity_list.add_argument("--task-id", help="filter events by task identifier")
    cmd_activity_list.add_argument(
        "--action", action="append", dest="actions", help="include only matching action; repeatable"
    )
    cmd_activity_list.add_argument(
        "--exclude-action",
        action="append",
        dest="exclude_actions",
        help="exclude matching action; repeatable",
    )
    cmd_activity_list.add_argument(
        "--hide-verify", action="store_true", help="hide verify.start and verify.ok events"
    )
    cmd_activity_list.add_argument(
        "--after-seq", type=int, default=0, help="return events with event_seq > N"
    )
    cmd_activity_list.add_argument("--limit", type=int, default=100, help="maximum events to return")
    cmd_activity_list.add_argument(
        "--format",
        choices=["json", "jsonl", "table"],
        default="json",
        help="output format (default: json)",
    )
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
    cmd_verify.add_argument(
        "--full", action="store_true", help="ignore snapshots and replay the full event store"
    )
    cmd_chain = sub.add_parser("chain", help="event-store hash chain commands")
    chain_sub = cmd_chain.add_subparsers(dest="chain_command", required=True)
    cmd_chain_init = chain_sub.add_parser("init", help="append a chain.anchor event")
    cmd_chain_init.add_argument(
        "--force", action="store_true", help="re-anchor an already anchored hash chain"
    )
    chain_sub.add_parser("verify", help="verify event-store hash chain")
    cmd_store = sub.add_parser("store", help="event-store maintenance commands")
    store_sub = cmd_store.add_subparsers(dest="store_command", required=True)
    cmd_store_repair = store_sub.add_parser("repair", help="quarantine a malformed final line and reproject")
    cmd_store_repair.add_argument("--dry-run", action="store_true", help="inspect without writing any files")
    cmd_status = sub.add_parser("status", help="summarize workspace state for human review")
    cmd_status.add_argument(
        "--format", choices=["table", "json"], default="table", help="output format (default: table)"
    )
    cmd_eligible = sub.add_parser("eligible", help="list eligible tasks and parallel groups")
    cmd_eligible.add_argument(
        "--format", choices=["json", "table"], default="json", help="output format (default: json)"
    )
    sub.add_parser("metrics", help="emit structured runtime metrics")

    cmd_input = sub.add_parser("input", help="local runner input commands")
    input_sub = cmd_input.add_subparsers(dest="input_command", required=True)
    cmd_input_binary = input_sub.add_parser("binary", help="stage binary input for a claimed task")
    cmd_input_binary.add_argument("task_id", help="claimed task identifier")
    cmd_input_binary.add_argument("source", help="source binary file path")
    cmd_input_binary.add_argument("--actor", required=True, help="actor staging the binary input")
    cmd_input_binary.add_argument("--size", required=True, type=int, help="expected file size in bytes")
    cmd_input_binary.add_argument("--sha256", required=True, help="expected SHA-256 hex digest")
    cmd_input_commands = input_sub.add_parser("commands", help="runner command capability input")
    input_commands_sub = cmd_input_commands.add_subparsers(dest="commands_command", required=True)
    cmd_input_commands_validate = input_commands_sub.add_parser(
        "validate", help="validate a command capability YAML file"
    )
    cmd_input_commands_validate.add_argument("path", help="path to command capability YAML file")
    cmd_input_commands_register = input_commands_sub.add_parser(
        "register", help="register a command capability YAML file for this runner"
    )
    cmd_input_commands_register.add_argument("path", help="path to command capability YAML file")
    cmd_input_commands_register.add_argument("--runner-id", default=None, help="override runner identifier")
    cmd_input_commands_show = input_commands_sub.add_parser("show", help="show registered commands input")
    cmd_input_commands_show.add_argument("--runner-id", default=None, help="filter by runner identifier")

    cmd_plugin = sub.add_parser("plugin", help="installable plugin commands")
    plugin_sub = cmd_plugin.add_subparsers(dest="plugin_command", required=True)
    cmd_plugin_list = plugin_sub.add_parser("list", help="list installed or available plugins")
    cmd_plugin_list.add_argument(
        "--available", action="store_true", help="list available plugins instead of installed"
    )
    cmd_plugin_list.add_argument(
        "--bundled", action="store_true", help="when listing available plugins, show bundled only"
    )
    cmd_plugin_list.add_argument(
        "--external", action="store_true", help="when listing available plugins, show external catalog only"
    )
    cmd_plugin_list.add_argument(
        "--format", choices=["json", "table"], default="json", help="output format (default: json)"
    )
    cmd_plugin_new = plugin_sub.add_parser("new", help="scaffold a plugin directory package")
    cmd_plugin_new.add_argument("plugin_id", help="new plugin identifier")
    cmd_plugin_new.add_argument("--directory", default=None, help="target directory for plugin scaffold")
    cmd_plugin_validate = plugin_sub.add_parser("validate", help="validate an available plugin")
    cmd_plugin_validate.add_argument("plugin_ref", help="plugin id or path to validate")
    cmd_plugin_doctor = plugin_sub.add_parser("doctor", help="diagnose a plugin package")
    cmd_plugin_doctor.add_argument("plugin_ref", help="plugin id or path to diagnose")
    cmd_plugin_install = plugin_sub.add_parser("install", help="install a plugin into this workspace")
    cmd_plugin_install.add_argument("plugin_ref", help="plugin id or path to install")
    cmd_plugin_install.add_argument("--dry-run", action="store_true", help="preview without emitting events")
    cmd_plugin_update = plugin_sub.add_parser("update", help="update an installed plugin in this workspace")
    cmd_plugin_update.add_argument("plugin_ref", help="plugin id or path to update")
    cmd_plugin_update.add_argument("--dry-run", action="store_true", help="preview without emitting events")
    cmd_plugin_remove = plugin_sub.add_parser("remove", help="remove an installed plugin from this workspace")
    cmd_plugin_remove.add_argument("plugin_id", help="installed plugin identifier to remove")
    cmd_plugin_remove.add_argument("--dry-run", action="store_true", help="preview without emitting events")
    cmd_plugin_status_sub = plugin_sub.add_parser(
        "status", help="show planned-vs-projected status per roadmap plugin"
    )
    cmd_plugin_status_sub.add_argument(
        "--detail",
        action="store_true",
        help="include per-task list (task_id, title, projected status)",
    )
    cmd_plugin_status_sub.add_argument(
        "--plugin",
        default=None,
        help="filter to one plugin filename (e.g. roadmap.sso-client.json)",
    )

    cmd_roadmap = sub.add_parser("roadmap", help="plugin roadmap execution commands")
    roadmap_sub = cmd_roadmap.add_subparsers(dest="roadmap_command", required=True)
    cmd_roadmap_list = roadmap_sub.add_parser("list", help="list roadmap executions")
    cmd_roadmap_list.add_argument("--detail", action="store_true", help="include detailed task summary")
    cmd_roadmap_list.add_argument(
        "--format", choices=["json", "table"], default="json", help="output format (default: json)"
    )
    cmd_roadmap_status = roadmap_sub.add_parser("status", help="show roadmap execution status")
    cmd_roadmap_status.add_argument("--detail", action="store_true", help="include detailed task summary")
    cmd_roadmap_activate = roadmap_sub.add_parser("activate", help="activate a plugin roadmap")
    cmd_roadmap_activate.add_argument("plugin_id", help="installed plugin identifier")
    cmd_roadmap_activate.add_argument(
        "--execution-id", default="default", help="roadmap execution identifier (default: default)"
    )
    cmd_roadmap_activate.add_argument(
        "--input", dest="input_path", default=None, help="optional input JSON path"
    )
    cmd_roadmap_activate.add_argument(
        "--dry-run", action="store_true", help="preview without emitting events"
    )
    for name, help_text in (
        ("pause", "pause a roadmap execution"),
        ("resume", "resume a roadmap execution"),
        ("deactivate", "deactivate a roadmap execution"),
    ):
        cmd = roadmap_sub.add_parser(name, help=help_text)
        cmd.add_argument("plugin_id", help="installed plugin identifier")
        cmd.add_argument(
            "--execution-id", default="default", help="roadmap execution identifier (default: default)"
        )
        cmd.add_argument("--dry-run", action="store_true", help="preview without emitting events")

    cmd_plugin_status = sub.add_parser(
        "plugin-status",
        help="show planned-vs-projected status per roadmap plugin (equivalent to 'esaa plugin status')",
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
    cmd_effects_recover.add_argument("--dry-run", action="store_true", help="preview without writing files")

    cmd_runner = sub.add_parser("runner", help="external runner telemetry commands")
    runner_sub = cmd_runner.add_subparsers(dest="runner_command", required=True)
    cmd_runner_metrics = runner_sub.add_parser("metrics", help="record external runner metrics")
    cmd_runner_metrics.add_argument("--file", default=None, help="JSON payload file, or '-' for stdin")
    cmd_runner_metrics.add_argument("--task-id", default=None, help="task identifier")
    cmd_runner_metrics.add_argument("--actor", default=None, help="actor identifier")
    cmd_runner_metrics.add_argument("--runner-id", default=None, help="runner identifier")
    cmd_runner_metrics.add_argument("--runner-kind", default=None, help="runner kind (e.g. codex, claude)")
    cmd_runner_metrics.add_argument("--model", default=None, help="model name used by runner")
    cmd_runner_metrics.add_argument("--command-surface", default=None, help="command surface invoked")
    cmd_runner_metrics.add_argument("--started-at", default=None, help="ISO-8601 start timestamp")
    cmd_runner_metrics.add_argument("--ended-at", default=None, help="ISO-8601 end timestamp")
    cmd_runner_metrics.add_argument("--latency-ms", type=int, default=None, help="execution latency in ms")
    cmd_runner_metrics.add_argument("--input-tokens", type=int, default=None, help="input token count")
    cmd_runner_metrics.add_argument("--output-tokens", type=int, default=None, help="output token count")
    cmd_runner_metrics.add_argument("--total-tokens", type=int, default=None, help="total token count")
    cmd_runner_metrics.add_argument("--cost-estimate", type=float, default=None, help="estimated cost")
    cmd_runner_metrics.add_argument("--status", default=None, help="execution status")
    cmd_runner_metrics.add_argument("--error-code", default=None, help="error code if execution failed")
    cmd_runner_metrics.add_argument("--correlation-id", default=None, help="correlation identifier")
    cmd_runner_metrics.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_scenario = sub.add_parser("scenario", help="[demo] deterministic operational scenarios")
    scenario_sub = cmd_scenario.add_subparsers(dest="scenario_command", required=True)
    cmd_scenario_hotfix = scenario_sub.add_parser("hotfix", help="[demo] run the demonstrable hotfix trace")
    cmd_scenario_hotfix.add_argument("--current", action="store_true", help="run in the current workspace")
    cmd_scenario_hotfix.add_argument("--issue-id", default="ISS-HOTFIX-TRACE", help="issue id for trace")

    # AUD-O0-045: curadoria de lessons propostas por agentes (operador).
    cmd_lesson = sub.add_parser("lesson", help="operator curation of agent-proposed lessons")
    lesson_sub = cmd_lesson.add_subparsers(dest="lesson_command", required=True)
    cmd_lesson_list = lesson_sub.add_parser("list", help="list lessons replayed from the event store")
    cmd_lesson_list.add_argument(
        "--status",
        choices=["proposed", "active", "experimental", "superseded", "archived"],
        default=None,
        help="filter by lesson status (proposed = waiting for the operator)",
    )
    cmd_lesson_list.add_argument(
        "--format", choices=["json", "table"], default="json", help="output format (default: json)"
    )
    for name, text in (
        ("approve", "activate a proposed lesson so it reaches the dispatch context"),
        ("reject", "archive a proposed lesson; it never reaches the dispatch context"),
    ):
        cmd_lesson_decide = lesson_sub.add_parser(name, help=text)
        cmd_lesson_decide.add_argument("lesson_id", help="lesson id, e.g. LES-0004")
        cmd_lesson_decide.add_argument("--reason", required=True, help="why the operator took this decision")
        cmd_lesson_decide.add_argument("--dry-run", action="store_true", help="validate without persisting")

    cmd_vocabulary = sub.add_parser("vocabulary", help="show protocol vocabulary mappings")
    cmd_vocabulary.add_argument("--profile", default=None, help="vocabulary profile name")

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


def _report_cli_error(code: str, message: str) -> int:
    """RF08: one short JSON line; traceback is opt-in, including exception causes."""
    lines = message.splitlines()
    msg = lines[0] if lines else code
    if len(msg) > 200:
        msg = msg[:197] + "..."
    print(json.dumps({"error_code": code, "error_message": msg}, ensure_ascii=True), file=sys.stderr)
    if os.environ.get("ESAA_DEBUG") == "1":
        traceback.print_exc(file=sys.stderr)
    return 1


def _build_adapter_from_args(args: Any) -> HttpLlmAdapter | None:
    if getattr(args, "command", None) != "run" or getattr(args, "adapter", "mock") != "http":
        return None
    url = args.llm_url
    if url:
        return HttpLlmAdapter(url=url, token=args.llm_token, timeout=args.llm_timeout)
    try:
        return HttpLlmAdapter.from_env()
    except ValueError as exc:
        raise ESAAError(WORKSPACE_INVALID, f"HTTP adapter configuration: {exc}") from exc


def _exit_code_for_result(args: Any, result: dict[str, Any]) -> int:
    if (
        args.command == "verification"
        and getattr(args, "verification_command", None) == "run"
        and result.get("status") not in {"passed", "dry_run"}
    ):
        return 2
    if result.get("verify_status") in {"mismatch", "corrupted"} or result.get("chain_status") == "broken":
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    if oplog_path_from_env() is not None:
        reset_concurrency_metrics()
    meta: dict[str, Any] = {
        "command": None,
        "runner": None,
        "root": None,
        "dry_run": False,
        "exit_code": 1,
        "error_code": None,
    }
    try:
        args = _build_parser().parse_args(argv)
        meta["command"] = " ".join(command_path(args))
        meta["runner"] = getattr(args, "runner", None)
        meta["dry_run"] = bool(getattr(args, "dry_run", False))
        if meta["runner"]:
            os.environ[ENV_RUNNER_ID] = meta["runner"]  # G08: precedencia CLI > env > default
        root = Path(args.root).resolve()
        meta["root"] = root
        service = ESAAService(root=root, adapter=_build_adapter_from_args(args))
        result = dispatch_cli(CliContext(root=root, service=service, args=args))
        if isinstance(result, int):
            meta["exit_code"] = result
            if result != 0:
                meta["error_code"] = "VERIFY_FAILED"
            return result
        print(_format_cli_output(result, getattr(args, "format", "json")))
        code = _exit_code_for_result(args, result)
        meta["exit_code"] = code
        if code != 0:
            meta["error_code"] = str(
                result.get("verify_status")
                or result.get("chain_status")
                or result.get("status")
                or "EXIT_NONZERO"
            )
        return code
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
        meta["exit_code"] = code
        meta["error_code"] = "INVALID_ARGUMENT" if code != 0 else None
        raise
    except ESAAError as exc:
        meta["error_code"] = exc.code
        meta["exit_code"] = _report_cli_error(exc.code, exc.message)
        return int(meta["exit_code"])
    except (json.JSONDecodeError, OSError, UnicodeError, yaml.YAMLError, SchemaError) as exc:
        meta["error_code"] = WORKSPACE_INVALID
        message = getattr(exc, "problem", None) or str(exc)
        meta["exit_code"] = _report_cli_error(WORKSPACE_INVALID, message)
        return int(meta["exit_code"])
    except Exception:
        meta["error_code"] = "INTERNAL_ERROR"
        meta["exit_code"] = 1
        raise
    finally:
        emit_oplog_entry(
            command=meta["command"],
            runner=meta["runner"],
            root=meta["root"],
            duration_ms=int((time.monotonic() - started) * 1000),
            exit_code=int(meta["exit_code"]),
            error_code=meta["error_code"],
            dry_run=bool(meta["dry_run"]),
        )


if __name__ == "__main__":
    raise SystemExit(main())
