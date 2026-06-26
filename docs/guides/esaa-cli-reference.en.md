# ESAA — CLI reference

🌐 [Português](esaa-cli-reference.md) · **English**

Reference for every `esaa` subcommand (package `esaa-core`, line
0.5.0b10). Syntaxes extracted from the CLI's real `--help`.

**Global flags** (before the subcommand):

```text
esaa [--root ROOT] [--runner RUNNER] [--version] <subcommand> ...
```

- `--root` — workspace root (the folder that contains `.roadmap/`). Default: `.`.
- `--runner` — runner identity stamped on every event (G08); may come from
  `ESAA_RUNNER_ID`. E.g.: `codex`, `claude-code`.

Almost every transition accepts `--dry-run`: it simulates the event, validates it
against the schema, and shows the resulting hash **without persisting**.

For commands that write events (`init`, `task create`, `claim`, `complete`,
`review`, `submit`, `issue`, `hotfix`, `activity`, `run`, `runner metrics`),
pass `--runner <id>` before the subcommand or set `ESAA_RUNNER_ID`.

---

## Workspace and canonical state

### `bootstrap` — install governance templates

```text
esaa bootstrap [--profile {public,production}] [--force]
```

Installs the contracts, schemas, and policies packaged in `.roadmap/`.
`public` is the default profile; `production` is the hardened variant.

### `init` — initialize clean state

```text
esaa init [--run-id RUN_ID] [--master-correlation-id ID] [--force]
```

Creates the event store and the projections; emits the reseed of the baseline
lessons (LES-0001/2/3) by event, never by manual edit.

### `project` — reproject read models

```text
esaa project
```

Rebuilds `roadmap.json`, `issues.json`, `lessons.json` deterministically from
`activity.jsonl`.

### `verify` — check consistency

```text
esaa verify [--chain]
```

Reprojects and compares the SHA-256 hash of the canonicalized projection →
`ok | mismatch | corrupted`. With `--chain`, it also validates the event-store
hash chain.

### `replay` — rebuild state at a point

```text
esaa replay [--until EVENT_SEQ|EVENT_ID] [--no-write]
```

Rebuilds the state up to the indicated event. `--no-write` computes without
writing the views — useful for historical auditing.

### `chain init` — anchor the hash chain

```text
esaa chain init [--force]
```

Adds a `chain.anchor` event that anchors the event-store hash chain.
Use `--force` only when you need to recreate the anchor explicitly.

### `snapshot` — checkpoint and compaction

```text
esaa snapshot --before N [--compact] [--dry-run]
```

Writes a projection checkpoint covering events with `event_seq <= N`.
`--compact` archives the included events beside the snapshot, keeping replay
auditable without the event store growing indefinitely.

### `activity clear` — reset the event store

```text
esaa activity clear [--force] [--dry-run] [--backup-dir DIR]
```

Backs up and clears `.roadmap/activity.jsonl`. Use `--dry-run` to inspect the
plan and `--force` to actually truncate. An administrative, destructive
operation: run `verify` before and after.

---

## Planning and dispatch

### `task create` — create a task

```text
esaa task create TASK_ID --kind {spec,impl,qa} --title TITLE
  [--description D] [--output PATH]... [--depends-on TASK]...
  [--target T]... [--boundary-grant FNMATCH] [--dry-run]
```

Appends an Orchestrator `task.create`. `--boundary-grant` grants an extra write
pattern for that task only (operator authority, T-2070).

### `eligible` — what can run now

```text
esaa eligible
```

Lists tasks with satisfied dependencies and the `parallel_groups` (groups
dispatchable in parallel without write conflict).

### `state` — a task's state

```text
esaa state TASK_ID
```

Shows the deterministic status and the **next expected action** — eliminates
"guessing whether it's claim or complete".

### `dispatch-context` — minimal context for the agent

```text
esaa dispatch-context TASK_ID
```

Returns the minimal dispatch package: the task, `expected_action`,
`allowed_actions`, the envelope schema slice, applicable active lessons, and
`runtime_capabilities` (if registered via `input commands`).

---

## Cycle transitions

### `claim` — claim (todo → in_progress)

```text
esaa claim TASK_ID --actor ACTOR [--notes NOTES] [--dry-run]
```

### `complete` — complete (in_progress → review)

```text
esaa complete TASK_ID --actor ACTOR --check CHECK [--check ...]
  [--file-updates FILE.json|-] [--notes NOTES]
  [--issue-id ISS] [--fixes F] [--dry-run]
```

`--file-updates` takes a JSON file (or stdin) with
`[{"path","content"}]` or the compact `edits` form with `base_sha256`.
Files are applied by the Orchestrator with atomic staging. `--check` is
required (min. 1; hotfix requires 2). Whoever completes must be whoever claimed.

### `review` — review (review → done | in_progress)

```text
esaa review TASK_ID --actor ACTOR --decision {approve,request_changes}
  [--task TASKS] [--dry-run]
```

Requires an actor with the QA role (`review_authorization=qa_role`). `approve`
makes the task `done` (terminal and immutable); `request_changes` returns it to
`in_progress`.

### `submit` — apply an agent.result envelope

```text
esaa submit [FILE] --actor ACTOR [--dry-run]
```

Validates and applies a full JSON envelope (`activity_event` +
`file_updates`) produced by an agent — the path used by LLM runners.
It passes through all workflow gates (WG-001..005) and uses a transactional append.

### `run` — automatic orchestration

```text
esaa run [--steps N] [--parallel N] [--adapter {mock,http}]
  [--llm-url URL] [--llm-token TOKEN] [--llm-timeout S]
  [--until-done] [--dry-run]
```

Runs dispatch waves: mock (tests/CI) or HTTP (LLM endpoint).
`--until-done` runs until no eligible task remains.

---

## Deviations, defects, and lessons

### `issue report` / `issue resolve`

```text
esaa issue report TASK_ID --actor ACTOR --issue-id ISS \
  --severity {low,medium,high,critical} --title TITLE \
  --symptom SYMPTOM --repro-step STEP [--repro-step STEP ...] \
  [--fixes TASK_ID] [--dry-run]

esaa issue resolve --issue-id ISS [--hotfix-task-id TASK_ID] [--dry-run]
```

Example:

```powershell
esaa --runner codex issue report T-1000 --actor agent-qa `
  --issue-id ISS-1000-DOCS --severity medium `
  --title "Guia incompleto" `
  --symptom "Sintaxe do comando operacional esta incompleta" `
  --repro-step "Executar esaa issue report --help" `
  --fixes T-1000
```

`issue.report` is the blocked agent's fail-closed output — it requires
`evidence.symptom` + `evidence.repro_steps`. The only action that accepts
`prior_status="done"` (reporting a bug on an immutable task).

### `hotfix create`

```text
esaa hotfix create --issue-id ISS --fixes TASK_ID \
  [--scope-patch PREFIX ...] [--dry-run]
```

Creates the corrective task for a defect in a `done` task: it requires an open
issue, a reference to the original task (which stays intact), and a declared
scope. The hotfix `complete` requires `issue_id`, `fixes`, and 2+ checks. In the
current core, `hotfix create` generates an `impl` task; `scope_patch` further
restricts writing but does not change the `task_kind` boundary. For purely
documentation fixes, create a new `spec` task with `boundary-grant` when needed.

### `reject` — record an invalid output

```text
esaa reject TASK_ID --error-code CODE --source-action ACTION
  --message MSG [--dry-run]
```

Appends `output.rejected` with a canonical code (`ACTION_COLLAPSE`,
`MISSING_CLAIM`, `PRIOR_STATUS_MISMATCH`, ...). Single source:
`src/esaa/reject_codes.py`.

### `vocabulary` — protocol vocabulary

```text
esaa vocabulary [--profile PROFILE]
```

Shows the canonical mappings (actions, reject codes) — by profile, if indicated.

---

## External runners

### `input commands` — per-runner command capabilities

```text
esaa input commands validate PATH
esaa input commands register PATH [--runner-id ID]
esaa input commands show [--runner-id ID]
```

Registers, in `.roadmap/runner-inputs/commands/<runner-id>.yaml`, the
capabilities YAML (shell surfaces, tools, rules). **Local to the
workspace**, non-canonical. Injected into `dispatch-context` as
`runtime_capabilities`.

### `runner metrics` — external runner telemetry

```text
esaa runner metrics [--file FILE|-] \
  [--task-id TASK_ID] [--actor ACTOR] [--runner-id ID] \
  [--runner-kind KIND] [--model MODEL] [--command-surface SURFACE] \
  [--started-at ISO] [--ended-at ISO] [--latency-ms N] \
  [--input-tokens N] [--output-tokens N] [--total-tokens N] \
  [--cost-estimate N] [--status {success,failed,cancelled,unknown}] \
  [--error-code CODE] [--correlation-id ID] [--dry-run]
```

In practice, provide at least `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface`, and `status` (or pass a JSON with those fields via `--file`).
Records evidence of external execution as a `runner.metrics` event — reserved
for the Orchestrator/operator, never emitted by agents.

### `metrics` — runtime metrics

```text
esaa metrics
```

Emits structured metrics of the workspace's current state.

---

## External plugins and roadmaps

### `plugin`

```text
esaa plugin list | new | validate | doctor | install | remove | status
```

Lifecycle of roadmap/input packages: scaffold (`new`), validation,
diagnosis (`doctor`), installation, and removal in the workspace.

### `roadmap`

```text
esaa roadmap list | status | activate | pause | resume | deactivate
```

Controls plugin roadmap executions. Installing does **not** activate: activation
is an explicit step — it avoids making tasks runnable by accident.

### `plugin-status`

```text
esaa plugin-status [--detail] [--plugin FILE.json]
```

Compares planned vs. projected per plugin; `--detail` lists task by task.

---

## Integration and recovery

### `process` — file inbox

```text
esaa process [--dry-run]
```

Processes pending files from `.roadmap/inbox/` (file-governed input channel).

### `effects recover` — recover file effects

```text
esaa effects recover [--dry-run]
```

Reapplies missing file effects from the forensic artifacts
(`.roadmap/artifacts/file-effects/`) — post-crash recovery of the atomic
commit. Use `--dry-run` to list what would be reapplied.

### `scenario hotfix` — demonstrable trace

```text
esaa scenario hotfix [--current] [--issue-id ISSUE_ID]
```

Runs the full operational hotfix scenario (issue → hotfix → cycle), useful for
validating the protocol end to end. Without `--current`, the scenario uses a
temporary workspace; with `--current`, it operates in the current workspace.

---

## See also

- [Practical scenarios (cookbook)](esaa-cenarios.en.md)
- [Getting started](esaa-getting-started.en.md)
- [Operating Codex and Claude Code as runners](esaa-runners-codex-claude-code.en.md)
- [Why use ESAA](esaa-why.en.md)
