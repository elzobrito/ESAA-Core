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
esaa bootstrap [--profile {public,production}] [--force] [--preserve-guides | --merge-guides]
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
  [--target T]... [--task-type TYPE]
  [--acceptance-criterion TEXT]...
  [--required-review-mode MODE]
  [--supersedes TASK]...
  [--boundary-grant FNMATCH] [--dry-run]
```

Appends an Orchestrator `task.create`. `--boundary-grant` grants an extra write
pattern for that task only (operator authority, T-2070).

Optional G07 fields:

- `--task-type`: operational intent (`feature`, `hotfix`, `audit`, `release`,
  `memory`, `governance`, `maintenance`). `--kind` continues to control actor
  and boundary.
- `--acceptance-criterion`: ordered acceptance criterion; may be repeated.
- `--required-review-mode`: requires typed review (`functional`, `security`,
  `regression`, `docs`, `governance`, `release`).
- `--supersedes`: declares that the new task replaces an existing task.
  `superseded_by` is derived by the projector, read-only, and does not change
  the superseded task status.

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
  [--review-mode MODE] [--task TASKS] [--dry-run]
```

Requires an actor with the QA role (`review_authorization=qa_role`). `approve`
makes the task `done` (terminal and immutable); `request_changes` returns it to
`in_progress`. If a task has `required_review_mode`, every review must provide a
matching `--review-mode`, including `request_changes`. Reviews with missing,
invalid, or mismatched modes fail before append to `activity.jsonl`.

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

### G07 lessons

Lessons accept `status` values `active`, `experimental`, `superseded`, or
`archived`. `active` and `experimental` may appear in `dispatch-context`;
`superseded` and `archived` remain auditable but are excluded from the active
context.

Filtering uses OR within the same dimension and AND across different
dimensions. The dimensions are `task_kinds`, `task_types`, `review_modes`,
`paths`, `actors`, and `runners`. The new contract represents `enforcement` as
an object:

```json
{
  "enforcement": {
    "mode": "require_review_mode",
    "value": "governance"
  }
}
```

Legacy shapes with `applies_to` remain accepted and are normalized internally
when needed. `require_boundary_grant` never expands permissions; it only
requires an explicit grant that already exists.

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

## Runtime architecture and operations

This reference collects details previously included in the root README. Load the
relevant topic; installed contracts govern a workspace even when they differ from
the templates published by the package.

### Authority, states and context

```text
Agent proposes -> Orchestrator validates -> Event store records -> Projection updates

todo --claim--> in_progress --complete--> review --approve--> done
                    ^                      |
                    +--- request_changes --+
```

Agents emit claim, complete, review or issue.report. Task creation, issue resolution,
provenance, metrics, file writes and materialization are Orchestrator operations.
The exact lists live in contracts and schemas. The harness executes agents;
it does not replace ESAA governance.

Minimal context uses schema_slice by action, filtered lessons/issues and completed
dependency interfaces without their bodies. Deterministic commands and exact edits
avoid repeated payloads; this is not a proven inference-cost reduction without
measuring real tokens. See the runner guide for envelopes, CRLF, UTF-8, base_sha256,
check minimums and review authorization.

Role resolution uses agents_swarm and runtime fallbacks. review_authorization
controls who reviews; completing still belongs to the actor that claimed.
Do not change policy to bypass a review.

### Tracked sources

These examples belong to tracked source and the governance bundle.

```text
.roadmap/AGENT_CONTRACT.yaml
.roadmap/ORCHESTRATOR_CONTRACT.yaml
.roadmap/RUNTIME_POLICY.yaml
.roadmap/STORAGE_POLICY.yaml
.roadmap/PROJECTION_SPEC.md
.roadmap/agent_result.schema.json
src/esaa/
tests/
```

### Paths created by operations

These paths may be absent in a clean workspace; they appear with the matching operation. Task documents enter through the governed workflow.

```text
.roadmap/plugins.lock.json
.roadmap/roadmaps.lock.json
.roadmap/plugin-inputs/
.roadmap/snapshots/
docs/spec/
docs/qa/
```

### Layout and projections

Contracts, schemas, storage/runtime policies, PROJECTION_SPEC and PARCER profiles
live in `.roadmap/`; code is in `src/esaa/` and tests in `tests/`.
Task documents live in `docs/spec/` and `docs/qa/`. The root README is an explicit
spec write exception in the default contract. Active boundaries take precedence.

Replay rebuilds roadmap, issues, lessons and project profile from events.
`verify` compares projections: `ok` confirms consistency; `mismatch` means a difference;
`corrupted` means invalid history; `unknown` does not establish verification.
A planned task without lifecycle events is not itself a mismatch.
Never fix a projection by editing it manually.

Baseline lessons are seeded by event and survive project/replay. Historical failures
should not become global instructions: respect each lesson's scope and enforcement.
Older terms such as promote, phase.complete, backlog and ready may be historical
or profile-specific; consult `esaa vocabulary --help`.

### Plugins and executions

Installation records `.roadmap/plugins.lock.json`; activation records
`.roadmap/roadmaps.lock.json` and exposes eligible tasks. Distinguish available and
installed packages from active executions. Pause hides an execution from eligible;
deactivation ends its use for new planning and is not synonymous with uninstall.

```bash
python -m esaa --runner codex plugin install ./security
python -m esaa --runner codex roadmap activate security --execution-id default
python -m esaa eligible
```

IDs use `<plugin-id>-<execution-id>-<local-task-id>`: `security-default-T-001`.
`.template.json` templates are not executable by themselves. Loose roadmaps are
legacy compatibility. External catalogs use ESAA_PLUGINS_HOME or `~/.esaa/plugins`,
with layout `<plugin>/<version>/plugin.json`. A package may contain no bundled
plugins; local directories remain installable. Copied inputs live in
`.roadmap/plugin-inputs/`. See the plugin guides for authoring and the full lifecycle.

### Onboarding and distributed guides

Bootstrap installs contracts and portable guidance. A consumer README is not a
copy of the Core README. AGENTS points to installed local files; the Claude guide
points to ../AGENTS.md. Reading the entire manual is not required.

Default mode rejects conflicts. `--preserve-guides` keeps existing guides;
`--merge-guides` retains the project region and refreshes the ESAA region;
`--force` permits overwriting allowlisted targets. Existing contracts still require
force to update. Preserve/merge are mutually exclusive. Invalid markers prevent
merge before governance writes. A root CLAUDE.md is not merged as though it were
.claude/CLAUDE.md. Bootstrap does not replace history, projections, backups or
snapshots. Existing workspaces do not migrate automatically.

```bash
python -m esaa --runner codex onboard --answers project-profile.json --dry-run
python -m esaa profile show
```

Onboarding records how to address the operator, derives the project profile and
creates a governed task chain. Pending seeds can be superseded by specific tasks;
clean init starts without demos, and `--with-demo-tasks` is explicit.

### Concurrency and transactional effects

`run --parallel` groups independent tasks while keeping serialized append.
Conflicts account for exact paths, directory prefixes, scope_patch and actual wave
effects. A store lock does not authorize concurrent edits to the same files.

```text
stage_and_compute -> append_transactional -> commit_staged
```

```json
{
  "task_id": "T-EXAMPLE",
  "files": ["src/example.py"],
  "effects": [{
    "path": "src/example.py",
    "before_sha256": null,
    "after_sha256": "<sha>",
    "bytes": 10,
    "encoding": "utf-8",
    "artifact_sha256": "<sha>",
    "artifact_path": ".roadmap/artifacts/file-effects/<sha>.json"
  }]
}
```

The example shows forensic orchestrator.file.write metadata. Content-addressed
artifacts support audit/replay. The transaction rereads events under lock, checks
expected sequence/hash, materializes before persistence and verifies the append.
Errors include STORE_LOCK_TIMEOUT, STALE_STATE_SEQ, STALE_STATE_HASH and
APPEND_VERIFY_FAILED. Failures do not authorize manual lock removal or store edits.

Admitted effects that did not commit can be recovered; the runtime cleans orphan
staging. Artifact verification detects ARTIFACT_MISSING, ARTIFACT_HASH_MISMATCH
and ARTIFACT_CONTENT_HASH_MISMATCH. Implementation details live in store.py and
file_effects.py; agents should not reimplement the transaction.

### Hotfix, snapshots and recovery

```text
issue.report -> hotfix.create -> claim -> complete -> review(approve) -> issue.resolve
```

Hotfix requires issue_id, fixes, scope_patch and two complete checks. Request errors:
HOTFIX_ISSUE_NOT_FOUND, HOTFIX_ISSUE_NOT_OPEN, HOTFIX_TARGET_NOT_FOUND,
HOTFIX_TARGET_NOT_DONE, HOTFIX_SCOPE_INVALID and HOTFIX_ALREADY_EXISTS.
The default hotfix scenario uses a temporary workspace; `--current` changes the real one.

```bash
python -m esaa snapshot --before 100 --compact --dry-run
python -m esaa replay --no-write
python -m esaa effects recover --help
```

Snapshots capture state and replay evidence. Compaction produces snapshot, archive,
tail and manifest; it requires verified state, consistent projections and a cutoff
within the last verified event. Missing archive/tail invalidates recovery.
Clearing history with `activity clear --force` is a destructive administrative
operation even though it creates a backup; run it only when explicitly authorized.
Use dry-run when available and do not confuse recovery with authorization to erase history.

### Runners and telemetry

External runners do not need native adapters for every provider. The generic HTTP
adapter receives context and returns an envelope; the optional token comes from ESAA_LLM_TOKEN.

```bash
ESAA_LLM_URL=http://127.0.0.1:8080/agent python -m esaa --runner codex run --adapter http --steps 2
```

runner.metrics records latency, runner, model, command surface, status, correlation
and known actual counts. Unknown data remains absent or null, without invented
costs. A deterministic CLI does not eliminate review judgment.
The Core error vocabulary is centralized in src/esaa/reject_codes.py.
