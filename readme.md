# ESAA - Event Sourcing for Autonomous Agents

<p align="center">
  <img src="docs/assets/esaa-logo.png" alt="ESAA state machine logo" width="960">
</p>

> Treat LLM agents as intention emitters under contract, not as unrestricted
> writers of code, state, or project history.

ESAA, Event Sourcing for Autonomous Agents, is a governance architecture and
event-sourced protocol for autonomous software engineering agents. It applies
the Event Sourcing pattern to agent workflows: the source of truth is an
append-only event log, and the current project state is a deterministic
projection of that log.

In one line:

```text
Agent proposes -> Orchestrator validates -> Event store records -> Projection updates
```

This repository contains the ESAA reference contracts, roadmap artifacts, tests,
and the local `esaa-core` runtime. The runtime is a Python CLI that applies the
protocol directly over `.roadmap/`; it does not use MCP.

Paper: [ESAA: Event Sourcing for Autonomous Agents in LLM-Based Software Engineering](https://arxiv.org/pdf/2602.23193)

## At A Glance

- Agents emit structured intentions; they do not write project state directly.
- The Orchestrator is the single writer for the event store and file effects.
- Every admitted transition is replayable from `.roadmap/activity.jsonl`.
- Read models such as `roadmap.json`, `issues.json`, and `lessons.json` are
  deterministic projections, not hand-edited truth.
- The runtime can advance known state transitions without spending LLM tokens.
- Patch-style `file_updates.edits` reduce repeated full-file payloads when only
  small changes are needed.

## Quickstart

Install the current beta package:

```bash
python -m pip install --upgrade --pre esaa-core
python -m esaa --version
```

For a pinned install:

```bash
python -m pip install esaa-core==0.5.0b9
python -m esaa --version
```

Start a clean workspace:

```bash
mkdir esaa-demo
cd esaa-demo
python -m esaa bootstrap --profile public
python -m esaa init
python -m esaa verify
python -m esaa eligible
```

Expected first signal: `verify` reports `verify_status: ok`. `eligible` reports
currently executable tasks from the active roadmap state.

`bootstrap` installs the full packaged governance bundle: contracts, schemas,
runtime/storage policy, projection spec, PARCER profiles, `README.md`, and
minimal agent guidance files (`AGENTS.md`, `.claude/CLAUDE.md`). It does not
create or overwrite `.roadmap/activity.jsonl`, read models, artifacts, backups,
or snapshots.

For production workspaces, use:

```bash
python -m esaa bootstrap --profile production
```

The production profile keeps independent QA review enabled and is intended to
be used with pinned package versions, backups, snapshots, `verify`, and
`runner.metrics`.

If the installed `esaa` script is not on your PATH, use `python -m esaa`; it is
the most portable invocation on Windows, Linux, and macOS.

## Usage Guides

> The guides below are currently written in Portuguese.

- [Getting started](docs/guides/esaa-getting-started.md) - from bootstrap to the
  first `todo -> in_progress -> review -> done` cycle.
- [Practical scenarios (cookbook)](docs/guides/esaa-cenarios.md) - 20 end-to-end
  situations: each command inside a real use case (init, tasks, plugins,
  runners, hotfix, auditing, concurrency).
- [CLI reference](docs/guides/esaa-cli-reference.md) - subcommands, syntax, and
  operational examples of `esaa`.
- [Codex and Claude Code as runners](docs/guides/esaa-runners-codex-claude-code.md) -
  `--runner` provenance, `dispatch-context`, envelopes, and metrics.
- [Why use ESAA](docs/guides/esaa-why.md) - problems solved by each protocol
  feature.

## Public Beta Status

Current package: `esaa-core 0.5.0b9`.

Current protocol/schema line: `0.4.1`. The package version marks beta runtime
readiness; it is not a protocol break.

Highlights in `0.5.0b9`:

- `input commands validate/register/show` lets a runner register local command
  capability YAML without making it canonical roadmap state.
- Registered command capabilities are injected into `dispatch-context` as
  `runtime_capabilities`, giving Codex, Claude Code, and other runners a compact
  view of available shells, tools, WSL helpers, and operating rules.
- The `0.5.0b8` file update hardening remains available: compact
  `file_updates.edits`, duplicate effective path rejection, `boundary_grant`,
  reduced dispatch payloads, and service decomposition.

## When To Use ESAA

Use ESAA when you need governed agent execution:

- autonomous or semi-autonomous coding agents working on roadmap tasks
- audit trails for who proposed, validated, and admitted each transition
- immutable task completion with hotfixes instead of history rewriting
- deterministic replay of state from an append-only event log
- multiple external runners such as Codex, Claude Code, or local scripts

ESAA is probably too much if you only need a one-off script, a throwaway
prototype, or an automation where direct file mutation without audit is
acceptable.

## Why ESAA Exists

LLM-based engineering agents are powerful, but their default execution model is
weakly governed. They can forget context, mix reasoning with side effects,
produce free-text outputs that do not fit a pipeline, and mutate files without a
durable record of why the change happened.

ESAA addresses three structural problems:

| Problem | ESAA response |
| --- | --- |
| Agents have no durable native state | Every admitted transition is persisted in an append-only event store |
| Long prompts degrade and lose relevant facts | The harness injects a purified context derived from projections and contracts |
| Probabilistic text breaks deterministic automation | Agents emit strict JSON intentions validated before any side effect |

The result is a workflow where an agent may propose work, report blockers, or
return a completion envelope, but only the Orchestrator can admit state,
persist events, apply file effects, and verify projections.

## Architecture

```text
ESAA governance/protocol
  -> Harness/runtime
    -> Orchestrator, single writer
      -> Agent, intention emitter
```

The layers are intentionally separate:

| Layer | Responsibility |
| --- | --- |
| ESAA | Defines the governance model, vocabulary, contracts, invariants, and event-sourced protocol |
| Harness | Prepares context, invokes agents, calls the Orchestrator, and coordinates execution cycles |
| Orchestrator | Validates outputs, enforces gates, appends events, applies approved effects, projects read models |
| Agent | Emits exactly one structured intention per invocation |

The central rule is simple: agents propose; the Orchestrator disposes.

```text
              dispatch context
        +----------------------------+
        |                            v
  +------------+   agent result   +----------------+   append   +----------------+
  |   Agent    | ----------------> | Orchestrator   | ---------> | Event Store    |
  | intention  |                   | deterministic  |            | activity.jsonl |
  +------------+ <---------------- +----------------+            +--------+-------+
       ^          output.rejected       |                                |
       |                                | project                         |
       |                                v                                v
       |                         +--------------+                 +--------------+
       +------------------------- | Read Models  | <--------------- | Replay/Hash  |
          purified view           | roadmap etc. |                 | Verification |
                                 +--------------+                 +--------------+
```

## Core Concepts

**Event store.** `.roadmap/activity.jsonl` is the append-only source of truth.
Events are ordered by `event_seq`, with no gaps, and are never edited manually.

**Read models.** `.roadmap/roadmap.json`, `.roadmap/issues.json`, and
`.roadmap/lessons.json` are deterministic projections. They are useful for UI,
dispatch, and operator inspection, but they are derived from the event store.

**Contracts.** `AGENT_CONTRACT.yaml`, `ORCHESTRATOR_CONTRACT.yaml`,
`RUNTIME_POLICY.yaml`, schemas, and PARCER profiles define what each layer may
do and what must be rejected.

**Boundaries.** Each task kind has read/write boundaries. For example, `spec`
tasks write documentation, `impl` tasks write `src/**` and `tests/**`, and `qa`
tasks write QA evidence and tests.

**Fail-closed operation.** If the system cannot validate a transition, it emits
or records a rejection or issue instead of guessing.

**Immutable done.** A `done` task is terminal. Defects in completed work are
handled through a hotfix task, not by reopening or rewriting history.

## Repository Layout

Tracked source and governance files in the reference repository:

```text
.roadmap/
  activity.jsonl                  append-only event store
  activity_future_templates.jsonl future templates, not consumed by runtime
  roadmap.json                    task projection/read model
  issues.json                     issue projection/read model
  lessons.json                    lessons projection/read model
  AGENT_CONTRACT.yaml             agent output and boundary contract
  ORCHESTRATOR_CONTRACT.yaml      workflow gates and single-writer rules
  RUNTIME_POLICY.yaml             attempts, cooldown, TTL, escalation
  STORAGE_POLICY.yaml             event-store persistence policy
  PROJECTION_SPEC.md              projection and hash rules
  agent_result.schema.json        strict agent result schema
  roadmap.schema.json             roadmap projection schema
  issues.schema.json              issue projection schema
  lessons.schema.json             lessons projection schema
  PARCER_PROFILE.*.yaml           prompt/control profiles

docs/operations/                  operator onboarding and runbooks
src/esaa/                         esaa-core runtime implementation
tests/                            protocol, CLI, and runtime tests
```

Runtime-created paths may not exist in a clean checkout. They are created by the
CLI when the matching operation runs:

```text
.roadmap/plugins.lock.json        created by plugin install
.roadmap/roadmaps.lock.json       created by roadmap activate
.roadmap/plugin-inputs/           created when plugin inputs are copied or supplied
.roadmap/snapshots/               created by snapshot or compaction commands
docs/spec/                        created by governed spec task file_updates
docs/qa/                          created by governed QA task file_updates
```

The root `readme.md` is an explicit `spec` boundary exception because it is the
public onboarding document for ESAA.

## State Machine

The active core state machine in v0.4.1 is:

```text
         claim              complete          review(approve)
[todo] ---------> [in_progress] ---------> [review] ---------> [done]
                       ^                       |
                       |                       |
                       +-----------------------+
                          review(request_changes)
```

Agent actions:

- `claim`
- `complete`
- `review`
- `issue.report`

Reserved Orchestrator actions:

- `run.start`, `run.end`
- `task.create`
- `hotfix.create`, `issue.resolve`
- `runner.metrics`
- `output.rejected`
- `orchestrator.file.write`
- `orchestrator.view.mutate`
- `verify.start`, `verify.ok`, `verify.fail`

## Agent Invocation Model

Governed execution is two-step. The harness invokes an agent once to claim a
task and a second time to complete it. The agent does not choose how many times
it is called; it reacts to the injected task status.

### Invocation 1: claim

Trigger: `task_status == "todo"`.

```json
{
  "activity_event": {
    "action": "claim",
    "task_id": "<task id>",
    "prior_status": "todo"
  }
}
```

No technical work is performed in this invocation. The only alternative is
`issue.report` when there is a material blocker before starting.

### Invocation 2: complete

Trigger: `task_status == "in_progress"` and `assigned_to` matches the actor.

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "<task id>",
    "prior_status": "in_progress",
    "notes": "<summary>",
    "verification": {
      "checks": ["<check performed>"]
    }
  },
  "file_updates": [
    {
      "path": "<allowed path>",
      "content": "<complete file content>"
    }
  ]
}
```

`file_updates` is legal only with `complete`. The Orchestrator validates schema,
workflow gates, boundaries, locks, and verification before applying any file
write.

Since `0.5.0b8`, a file update can also be sent as exact edits:

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "<task id>",
    "prior_status": "in_progress",
    "verification": {
      "checks": ["edit validated"]
    }
  },
  "file_updates": [
    {
      "path": "src/esaa/service.py",
      "base_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "edits": [
        {
          "old_string": "exact old text",
          "new_string": "replacement text",
          "replace_all": false
        }
      ]
    }
  ]
}
```

Edit semantics are fail-closed:

- `base_sha256` must match the current bytes of the target file.
- `old_string` is matched against the progressively edited UTF-8 text.
- Newlines are exact; CRLF is not normalized to LF.
- Non-UTF-8 targets are rejected.
- Multiple matches require `replace_all: true`.
- Rejections use structured codes such as `EDIT_BASE_MISMATCH`,
  `EDIT_TARGET_NOT_FOUND`, `EDIT_AMBIGUOUS`, and `EDIT_INVALID`.

### Review

When a task is in `review`, a QA-capable actor may approve it or request
changes:

```json
{
  "activity_event": {
    "action": "review",
    "task_id": "<task id>",
    "prior_status": "review",
    "decision": "approve",
    "tasks": ["<task id>"]
  }
}
```

`approve` moves the task to `done`. `request_changes` returns it to
`in_progress`.

**Role-based authorization (default).** Since v0.4.1,
`.roadmap/RUNTIME_POLICY.yaml#review_authorization` defaults to `"qa_role"`:

- `complete` continues to require `actor == assigned_to` (owner lock preserved).
- `review` requires `runtime_policy.resolve_role(actor) ∈ {qa, orchestrator}`.
  An owner without a QA role attempting to review their own work is rejected
  with `REVIEW_ROLE_VIOLATION`.

Role resolution checks `.roadmap/agents_swarm.yaml` (`agents[<actor>].role`)
and falls back to a name heuristic (`agent-qa*` → "qa";
`agent-orchestrator*` → "orchestrator"). Set `review_authorization: "owner"`
to restore the legacy mode where the owner reviews their own task.

### Issue report on `done`

`issue.report` is the only action permitted on a `done` task. The schema
allows `prior_status="done"` exclusively for this action, preserving forensic
evidence about the immutable task. All other actions on `done` are rejected
with `IMMUTABLE_DONE_VIOLATION`.

## Operating Modes

### Read-only

Use read-only mode when the user asks for inspection, explanation, diagnosis,
project status, or architectural analysis. No governed transition is started:
no `claim`, no `complete`, no `review`, and no `file_updates`.

Recommended closure block for read-only responses:

```text
- Task ID: N/A
- Summary: <what was inspected>
- Changed files: None.
- Tests run: None.
- ESAA verification: Not run.
- ESAA closure status: Not applicable - read-only request.
- Blockers, if any: <blockers>
```

### Governed execution

Use governed execution when work must be performed against a task: implement,
fix, refactor, generate files, update docs, or run a roadmap task. The harness
must admit the task through the state machine instead of letting an agent mutate
state directly.

### Deterministic no-token execution

When the state transition is known and does not require LLM reasoning,
`esaa-core` can drive the state machine directly through CLI commands. This
lets the harness control `claim`, `complete`, `review`, issue handling, hotfixes,
metrics, projection, and verification without spending tokens.

## Token Reduction Model

ESAA does not make model inference cheaper by itself. It reduces avoidable token
use around governed engineering work:

- compact projections and contracts replace repeated full repository summaries
- `dispatch-context` injects only the task-relevant operational state
- deterministic CLI transitions handle known workflow moves without an LLM call
- `file_updates.edits` can send small exact patches instead of full file bodies
- a decomposed runtime makes future analysis less likely to load one large
  service module for unrelated questions

This is a technical reduction in repeated context and payload size, not a
substitute for measuring provider-side input/output tokens when a real runner
is used.

## Workflow Gates

The Orchestrator applies workflow gates before persistence:

| Gate | Rule | Reject code |
| --- | --- | --- |
| WG-001 | `complete` and `review` require the correct previous state | `MISSING_CLAIM` |
| WG-002 | `complete` requires verification; `file_updates` requires `complete` | `MISSING_VERIFICATION` or `MISSING_COMPLETE` |
| WG-003 | `prior_status` must match the current projected status | `PRIOR_STATUS_MISMATCH` |
| WG-004 | Only the actor that claimed a task may complete it | `LOCK_VIOLATION` |
| WG-005 | One output contains exactly one `activity_event` | `ACTION_COLLAPSE` |
| WG-006 | Any action on `done` (except `issue.report`) is rejected | `IMMUTABLE_DONE_VIOLATION` |
| WG-007 | Under `review_authorization=qa_role`, reviewer must have role `qa`/`orchestrator` | `REVIEW_ROLE_VIOLATION` |

`PRIOR_STATUS_MISMATCH` is treated as context lag and does not consume an
attempt. Other gate failures may consume attempts according to runtime policy.

The canonical vocabulary of all reject codes is centralized in
`src/esaa/reject_codes.py` (`WORKFLOW_GATE_CODES`, `OPERATIONAL_CODES`,
`HOTFIX_CODES`, `ALL_CODES`). `tests/test_reject_codes_inventory.py` asserts
every `ESAAError(code, ...)` emitted in the engine is registered.

## Event Store And Projection

The event store records admitted facts. Projection is a pure replay operation
that rebuilds read models from events:

```text
activity.jsonl -> project_events() -> roadmap/issues/lessons -> canonical hash
```

Verification compares the projected state with stored read models:

```cmd
set PYTHONPATH=src
python -m esaa --root . verify
```

Status meanings:

| Status | Meaning |
| --- | --- |
| `ok` | stored read models match deterministic replay |
| `mismatch` | a read model diverges from replay |
| `corrupted` | the event store cannot be parsed or sequenced |
| `unknown` | verification has not established a result |

Projection and verification are the reason ESAA can support audit, replay,
forensic analysis, and recovery after interrupted runs.

## Roadmaps And Plugins

Planned work may come from the main roadmap or from installed plugin roadmap
executions. Installing a plugin does not make its tasks executable. A plugin
roadmap must be explicitly activated before `eligible` can see its tasks.

Plugin lifecycle state is separate from roadmap execution state:

- `available`: bundled or external catalog plugin can be installed. A clean
  source distribution may ship with no bundled plugins; local directory plugins
  are installed by path.
- `installed`: plugin is locked in `.roadmap/plugins.lock.json`
- `active`: a plugin roadmap execution is locked in `.roadmap/roadmaps.lock.json`
- `paused`: installed and configured, but hidden from `eligible`
- `deactivated`: no longer used for new planned work

Task ids emitted from plugin roadmaps are namespaced with dashes:

```text
<plugin-id>-<execution-id>-<local-task-id>
```

For example, internal plugin task `T-001` from plugin `security` becomes
`security-default-T-001`. This avoids global task-id collisions while keeping
the plugin's local task ids readable in plugin metadata.

Loose `.roadmap/roadmap.*.json` files are retained only as temporary
compatibility. Files ending in `.template.json` are never executable by
themselves; templates must be installed as plugins and activated as roadmap
executions.

A roadmap entry without lifecycle events is planned work, not a mismatch. A real
mismatch occurs when the event log and projection contradict each other, for
example when the log proves a task is `done` but a read model still shows it as
`todo`.

## Local Runtime: esaa-core

The public CLI is exposed as a Python module and as a console script.
`python -m esaa` is the safest cross-platform form:

```bash
python -m esaa --help
```

If the script directory is on your PATH, this also works:

```bash
esaa --help
```

When developing from this repository instead of an installed wheel, always set
the local source path first. Otherwise Python may import an older installed
wheel instead of the checkout you are editing.

```powershell
$env:PYTHONPATH='src'
python -m esaa --root . --help
```

On Linux/macOS:

```bash
PYTHONPATH=src python -m esaa --root . --help
```

New external workspaces should run `esaa bootstrap` before `esaa init` so the
full governance bundle, README, and minimal agent guidance files are present.

`esaa-core` is the deterministic runtime in this repository. It exposes the
Orchestrator operations through `python -m esaa`.

PowerShell:

```powershell
$env:PYTHONPATH='src'
python -m esaa --root . --help
```

CMD:

```cmd
set PYTHONPATH=src
python -m esaa --root . --help
```

Top-level commands:

```text
init
run
submit
claim
complete
review
state
dispatch-context
reject
task
issue
hotfix
activity
process
project
verify
eligible
metrics
plugin
roadmap
runner
scenario
vocabulary
snapshot
replay
```

The CLI is not a replacement for ESAA. It is a local harness/runtime surface
that applies ESAA rules.

## Common Usage

### Inspect state

```cmd
set PYTHONPATH=src
python -m esaa --root . state TASK-ID
python -m esaa --root . eligible
python -m esaa --root . metrics
python -m esaa --root . verify
```

### Create a task

`task create` emits a deterministic `task.create` event and validates the
projected roadmap against `.roadmap/roadmap.schema.json`.

```cmd
python -m esaa --root . task create README-1803 ^
  --kind spec ^
  --title "Update README" ^
  --description "Refresh public onboarding docs" ^
  --target documentation ^
  --output readme.md
```

### Advance a task without LLM tokens

```cmd
python -m esaa --root . claim README-1803 --actor agent-spec
python -m esaa --root . complete README-1803 --actor agent-spec --check "README reviewed" --file-updates updates.json
python -m esaa --root . review README-1803 --actor agent-qa --decision approve
```

`complete --file-updates` expects a JSON array:

```json
[
  {
    "path": "readme.md",
    "content": "# full file content\n"
  }
]
```

### Process submitted envelopes

```cmd
python -m esaa --root . submit --actor agent-spec agent-result.json
python -m esaa --root . process
```

Use this when an external harness places agent outputs in the expected inbox or
hands an explicit result file to the core.

### Manage plugins and roadmap executions

```cmd
python -m esaa --root . plugin list --available
python -m esaa --root . plugin list --available --bundled
python -m esaa --root . plugin list --available --external
python -m esaa --root . plugin new security
python -m esaa --root . plugin validate ./security
python -m esaa --root . plugin doctor ./security
python -m esaa --root . plugin install ./security
python -m esaa --root . plugin list
python -m esaa --root . roadmap activate security --execution-id default
python -m esaa --root . roadmap status --detail
python -m esaa --root . eligible
```

Plugins are directory packages with `plugin.json` in the root. `plugin new`
creates a valid starter package. `plugin validate` and `plugin install` accept a
bundled/external plugin id when one is available, or an explicit local directory
such as `./security`. The reference package does not require bundled plugins.

`plugin install` records the package in `.roadmap/plugins.lock.json`. It does
not affect `eligible`. `roadmap activate` records an execution in
`.roadmap/roadmaps.lock.json`, copies the plugin input example to
`.roadmap/plugin-inputs/` when needed, validates the local input against the
plugin schema, and exposes namespaced planned tasks such as
`security-default-T-001`.

External catalog plugins are discovered under `%USERPROFILE%\.esaa\plugins`
or the directory pointed to by `ESAA_PLUGINS_HOME`, using this layout:

```text
plugins/
  security/
    1.0.0/
      plugin.json
      roadmap.template.json
```

Pause, resume, and deactivate roadmap executions without uninstalling the
plugin:

```cmd
python -m esaa --root . roadmap pause security --execution-id default
python -m esaa --root . roadmap resume security --execution-id default
python -m esaa --root . roadmap deactivate security --execution-id default
python -m esaa --root . plugin remove security
```

## External Runners And Telemetry

ESAA does not require native Anthropic, OpenAI, or Gemini adapters when the
agent is an external runner such as Claude Code, Codex, Antigravity, or another
tool that opens the project and executes the ESAA CLI. In that model, the
provider-specific environment lives outside the core. The core needs the
admitted result and telemetry evidence.

`runner.metrics` records external runner evidence:

```cmd
python -m esaa --root . runner metrics ^
  --task-id README-1803 ^
  --actor agent-spec ^
  --runner-id codex-desktop ^
  --runner-kind codex ^
  --model gpt-5 ^
  --command-surface "python -m esaa claim/complete/review" ^
  --latency-ms 1250 ^
  --status success ^
  --correlation-id CID-README-1803
```

Metrics can include:

- latency
- input, output, and total tokens when known
- runner kind
- model
- status
- error code
- gate rejection counts
- attempt counts

Unknown provider values remain `null` or absent from numeric aggregates. The
core does not invent token usage or cost.

The generic HTTP adapter remains useful when an LLM endpoint can accept a
dispatch context and return an ESAA agent result envelope:

```powershell
$env:PYTHONPATH='src'
$env:ESAA_LLM_URL='http://127.0.0.1:8080/agent'
$env:ESAA_LLM_TOKEN='<optional-token>'
python -m esaa --root . run --adapter http --steps 2
```

## Parallel Dispatch And Write Conflicts

`eligible` reports executable tasks and `parallel_groups`:

```cmd
python -m esaa --root . eligible
python -m esaa --root . run --parallel 4 --until-done
```

Parallel waves run independent tasks concurrently while preserving serial append
to `activity.jsonl`. The Orchestrator remains the only writer.

Write conflict policy covers:

- exact file conflicts, such as `docs/spec/a.md` vs `docs/spec/a.md`
- directory-prefix conflicts, such as `docs/spec/` vs `docs/spec/a.md`
- hotfix writes constrained by `scope_patch`
- effective `file_updates.path` conflicts admitted in the same wave

Conflicting writes are rejected before the second side effect is applied.

## Hotfix Workflow

A completed task is immutable. A defect in a `done` task follows this flow:

```text
issue.report -> hotfix.create -> claim -> complete -> review(approve) -> issue.resolve
```

Hotfix tasks require:

- reference to the original `issue_id`
- reference to the task being fixed
- `scope_patch`
- at least two verification checks on `complete`
- final `issue.resolve` after approval

**Validation codes.** `build_hotfix_event` calls `validate_hotfix_request`
internally and raises `ESAAError` with one of the following structured codes
when the request is invalid:

| Code | Meaning |
| --- | --- |
| `HOTFIX_ISSUE_NOT_FOUND` | `issue_id` absent or not present in projection |
| `HOTFIX_ISSUE_NOT_OPEN` | issue exists but is already resolved |
| `HOTFIX_TARGET_NOT_FOUND` | `fixes` points to a non-existent task |
| `HOTFIX_TARGET_NOT_DONE` | target is immutable-done but its status is not `done` |
| `HOTFIX_SCOPE_INVALID` | `scope_patch` empty or missing |
| `HOTFIX_ALREADY_EXISTS` | duplicate hotfix for the same `issue_id` |

`validate_hotfix_request` is also exported for direct callers (tests, audit
checkers) that want validation without producing an event.

Example:

```cmd
python -m esaa --root . issue report T-1000 --actor agent-qa --issue-id ISS-1 --severity medium --title "Issue" --symptom "Observed problem" --repro-step "Reproduce it" --fixes T-1000
python -m esaa --root . hotfix create --issue-id ISS-1 --fixes T-1000 --scope-patch src/hotfix/
python -m esaa --root . claim HF-ISS-1 --actor agent-hotfix
python -m esaa --root . complete HF-ISS-1 --actor agent-hotfix --issue-id ISS-1 --fixes T-1000 --check unit --check regression --file-updates updates.json
python -m esaa --root . review HF-ISS-1 --actor agent-qa --decision approve
python -m esaa --root . issue resolve --issue-id ISS-1 --hotfix-task-id HF-ISS-1
```

Operational scenario:

```cmd
python -m esaa --root . scenario hotfix
python -m esaa --root . scenario hotfix --current --issue-id ISS-DEMO
```

The default scenario uses a temporary workspace. `--current` appends real events
to the current repository.

## Snapshots And Compaction

Snapshots capture projected state and replay evidence at an event boundary.
Compaction is staged and auditable: it writes a snapshot, archive, tail, and
manifest instead of silently destroying history.

```cmd
python -m esaa --root . snapshot --before 100 --dry-run
python -m esaa --root . snapshot --before 100 --compact --dry-run
python -m esaa --root . snapshot --before 100 --compact
```

Compaction refuses unsafe states:

- `verify_status != ok`
- missing or mismatched projections
- `--before` above the last verified event
- missing archive or tail during replay checks

## File Effects And Atomic Transactions

Since v0.4.1, `file_updates` produced by an agent on `complete` go through a
three-stage transaction that prevents partial writes when the append fails:

```text
stage_and_compute (file_effects.py)
  -> append_transactional (store.py)        # parse + revalidate + decide-seq + append + project
    -> commit_staged (file_effects.py)      # os.replace into final paths
       on failure -> discard_staged
```

The `orchestrator.file.write` event carries forensic metadata about every
applied effect:

```json
{
  "task_id": "<task>",
  "files": ["<path>"],
  "effects": [
    {
      "path": "<path>",
      "before_sha256": "<sha|null>",
      "after_sha256": "<sha>",
      "bytes": <n>,
      "encoding": "utf-8",
      "artifact_sha256": "<sha>",
      "artifact_path": ".roadmap/artifacts/file-effects/<sha>.json"
    }
  ]
}
```

Each effect's content is also persisted as a content-addressed artifact in
`.roadmap/artifacts/file-effects/<sha>.json`, enabling deterministic
replay/audit. `file_effects.verify_artifact()` returns `ARTIFACT_MISSING`,
`ARTIFACT_HASH_MISMATCH`, or `ARTIFACT_CONTENT_HASH_MISMATCH` on tampering.

Recovery after interruption is automatic: `service.recover_file_effects()`
(CLI: `esaa effects recover`) re-applies effects from admitted events
that did not commit. Staged files that never reached commit are cleaned by
`cleanup_orphan_staging()`.

### Serializable append

`store.append_transactional(root, build_events_fn, expected_first_seq, expected_projection_hash)`
acquires the file lock on `activity.jsonl.lock`, re-parses the store inside
the critical section, validates expected sequence and projection hash, and
only then commits the new events plus projections. Reject codes:

| Code | Meaning |
| --- | --- |
| `STORE_LOCK_TIMEOUT` | lock not acquired within timeout |
| `STALE_STATE_SEQ` | `expected_first_seq` no longer matches `next_event_seq` |
| `STALE_STATE_HASH` | `expected_projection_hash` no longer matches |

Concurrent multi-process appends cannot produce duplicate `event_seq` or stale
projections.

## Lessons

Lessons are projected from `.roadmap/lessons.json` and injected by the
Orchestrator when relevant. Active lessons are constraints, not suggestions.

Current core lessons include:

- never collapse `claim` and `complete` in one output
- never include `file_updates` without `action=complete`
- always include coherent `prior_status`

This makes repeated failures teach the protocol without relying on a human to
remember every historical rejection.

**Baseline lessons reseed by event.** `service.init` emits an
`orchestrator.view.mutate(target=lessons, change=baseline_reseed)` event
carrying the canonical `BASELINE_LESSONS` (LES-0001/2/3). The projector
reconstructs `lessons.json` deterministically from replay — no manual edit
of the read model is needed, and lessons survive `esaa project`/`esaa replay`.

## Vocabulary Evolution

The paper and older snapshots may mention terms such as `promote`,
`phase.complete`, `backlog`, or `ready`. In core v0.4.1, those are historical
terms or profile-specific vocabulary. The active core machine uses:

- statuses: `todo`, `in_progress`, `review`, `done`
- actions: `claim`, `complete`, `review`, `issue.report`

Inspect mappings:

```cmd
python -m esaa --root . vocabulary
python -m esaa --root . vocabulary --profile core-v0.4.1
```

## Administrative Commands

Clear the event store only when deliberately resetting a workspace. The command
creates a backup first:

```cmd
python -m esaa --root . activity clear --force
```

Use dry-run when available before destructive operations:

```cmd
python -m esaa --root . activity clear --force --dry-run
```

Reproject read models:

```cmd
python -m esaa --root . project
```

Replay without writing:

```cmd
python -m esaa --root . replay --no-write
```

## Development

Install dependencies in a virtual environment if desired, then run the test
suite with the local source path:

```cmd
set PYTHONPATH=src
python -m pytest -q
```

Current coverage includes:

- strict agent result validation
- state machine transitions
- deterministic task commands
- installable plugins and roadmap execution eligibility
- external runner telemetry
- hotfix lifecycle and production trace
- parallel dispatch and write conflicts
- snapshot and staged compaction
- vocabulary mapping
- filesystem locking for append-only writes
- schema strictness for `task create`

## Operational Rules

- Do not edit `.roadmap/activity.jsonl` manually.
- Do not edit read models by hand; reproject them from the event store.
- Do not mark tasks `done` directly; only approved review can do that.
- Do not reopen `done` tasks; use hotfix.
- Do not treat ESAA as a mere harness; the harness is one layer governed by
  ESAA.
- Do not assume native provider adapters are required when the real runner is
  Claude Code, Codex, Antigravity, or another external agent tool.
- Prefer deterministic commands when the state machine can advance without an
  LLM call.
- Treat projection drift as a state integrity issue, not as a reason to
  hand-edit projections.

## Citation

```bibtex
@article{santos2026esaa,
  title={ESAA: Event Sourcing for Autonomous Agents in LLM-Based Software Engineering},
  author={Santos Filho, Elzo Brito dos},
  year={2026},
  note={Preprint}
}
```

## License

MIT

## Author

Elzo Brito dos Santos Filho
