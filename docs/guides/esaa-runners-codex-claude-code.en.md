# Operating Codex and Claude Code as ESAA runners

🌐 [Português](esaa-runners-codex-claude-code.md) · **English**

ESAA does not use MCP. Runners integrate through the local CLI and files.
Read the sections needed for the current action; this guide is not a mandatory itinerary.

## Identity and context

A runner is the execution software; an actor is a logical role. One runner can
operate several roles, but that does not establish review by another model or human.
The Orchestrator validates and applies effects; the actor that claims must complete.

```bash
python -m esaa --root <workspace> --runner codex <command> ...
```

Replace `codex` with the actual runner; alternatively set `ESAA_RUNNER_ID`.
Strict mode requires registration in `.roadmap/agents_swarm.yaml`.
Do not include `runner` in the envelope: the Orchestrator stamps provenance.

```bash
python -m esaa eligible
python -m esaa state T-EXAMPLE
python -m esaa dispatch-context T-EXAMPLE
```

`dispatch-context` supplies `task`, allowed actions, `schema_slice` and correlation.
Lessons are filtered by action and scope. For `complete`, it includes boundaries,
dependency interfaces and filtered issues; for `review`, completed verification
when available. Project profile and runner capabilities depend on local registration.
Spec and file contents are not guaranteed in context: retrieve the relevant
references without scanning the entire repository. Read boundaries are permissions,
not a list of files that must all be loaded.

## Claim, delivery and review

`claim` and `complete` are separate submissions, with one `activity_event` per envelope
and a coherent `prior_status`. This does not limit a task to two invocations:
review, requested changes and retries follow the state machine.
Strict JSON applies to submitted envelopes, not to conversation with the user.

### Claim

For an eligible `todo` task:

```json
{"activity_event":{"action":"claim","task_id":"T-EXAMPLE","prior_status":"todo"}}
```

```bash
python -m esaa --runner codex submit --actor agent-impl claim.json
```

### Complete and file effects

For `in_progress`, the responsible actor supplies artifacts and actual verification:

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-EXAMPLE",
    "prior_status": "in_progress",
    "verification": {"checks": ["affected behavior verified"]}
  },
  "file_updates": [{"path": "src/example.py", "content": "VALUE = 1\n"}]
}
```

The example assumes an impl task with an authorized path; adapt it to the task's
criteria. `file_updates` is allowed only with `complete`; final effects belong to
the Orchestrator. An entry may also use exact edits instead of `content`:

```json
{
  "path": "src/example.py",
  "base_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "edits": [{"old_string": "VALUE = 1", "new_string": "VALUE = 2", "replace_all": false}]
}
```

Replace the illustrative hash with SHA-256 of the current file bytes.
Edits apply progressively to UTF-8 text; preserve exact newlines, including CRLF.
Multiple matches require `replace_all=true`; non-UTF-8 files are rejected.
Codes: `EDIT_BASE_MISMATCH`, `EDIT_TARGET_NOT_FOUND`, `EDIT_AMBIGUOUS`, `EDIT_INVALID`.
Resolution precedes effect validation, resource limits, staging and artifacts.

```bash
python -m esaa --runner codex submit --actor agent-impl complete.json --dry-run
python -m esaa --runner codex submit --actor agent-impl complete.json
python -m esaa verify
```

Dry-run is optional. Before complete, satisfy acceptance criteria and perform
relevant verification; when requested, continue through execution, inspection
and correction. Contract minimums: spec/impl/qa = 1 check; hotfix = 2.
Complete is neither approval nor authorization to publish.

### Review and done

```json
{"activity_event":{"action":"review","task_id":"T-EXAMPLE","prior_status":"review","decision":"approve","tasks":["T-EXAMPLE"]}}
```

```bash
python -m esaa --runner codex review T-EXAMPLE --actor agent-qa --decision approve
```

The `review_authorization=qa_role` policy admits QA/orchestrator roles;
an owner without that role receives `REVIEW_ROLE_VIOLATION`. Respect the task's
required review mode. `request_changes` returns to `in_progress`; `approve` reaches
`done`. Never reopen done: report an issue and follow hotfix, preserving the original
task. An issue on done must declare `prior_status` as `done`.

## Autonomy and blockers

Queries are read-only, without transitions; report useful results and limitations.
Within the authorized scope, investigate accessible information and resolve
reversible local choices without approval at each step. Local preparation and
validation do not authorize direct final effects or unauthorized external operations.

Obtain a decision before changing material requirements or permissions. Report
persistent context, dependency or boundary blockers with evidence; information
missing from the prompt alone does not establish a blocker.

```json
{
  "activity_event": {
    "action": "issue.report",
    "task_id": "T-EXAMPLE",
    "prior_status": "in_progress",
    "issue_id": "ISS-EXAMPLE",
    "severity": "medium",
    "title": "Required dependency is unavailable",
    "evidence": {"symptom": "Required source cannot be obtained", "repro_steps": ["Inspect the dependency reference"]}
  }
}
```

Lessons using `reject`, `require_field` and `require_step` are mandatory.
Consider `warn` without imposing a blocker or fixed acknowledgment text unless
the lesson itself requires it.

## Concurrency and integrity

The current runtime provides locks with PID, host and timestamp, transactional
rereads under lock and post-append verification. The CLI handles contention and
lock recovery according to its rules; never remove locks manually. Do not extend
these guarantees to older versions or concurrent edits to the same files.

Do not take over another actor's tasks. Stop the affected operation on
`STORE_LOCK_TIMEOUT`, `JSONL_INVALID`, `EVENT_SEQ_*`, `APPEND_VERIFY_FAILED` or
integrity failure. Do not bypass the error. The runtime handles stale-state
conflicts; if they persist, refresh context before a new valid submission.
Run `verify` after governed writes.

## Operational references

Gates, fields and limits come from `.roadmap/AGENT_CONTRACT.yaml`,
`ORCHESTRATOR_CONTRACT.yaml`, `agent_result.schema.json` and `RUNTIME_POLICY.yaml`.
Attempt defaults are 3 attempts, a 2-minute cooldown and a 30-minute TTL;
`PRIOR_STATUS_MISMATCH` does not consume an attempt. Consult the installed policy.

When the environment needs specialized command guidance, register its actual
capabilities. Registration is local to the workspace and only then injected into
dispatch. Telemetry must use observed values; do not invent token counts or costs.

```bash
python -m esaa --runner codex input commands register <capabilities.yaml>
python -m esaa --runner codex input commands show
python -m esaa runner metrics --help
```

Direct transition commands avoid another LLM call; they do not replace the
assessment required for a review decision. PARCER profiles are references by role,
not required reading for every task.

## See also

- [Getting started](esaa-getting-started.en.md)
- [CLI reference](esaa-cli-reference.en.md)
- [Why use ESAA](esaa-why.en.md)
