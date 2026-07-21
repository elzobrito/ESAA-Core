# ESAA — Practical scenarios (cookbook)

🌐 [Português](esaa-cenarios.md) · **English**

This guide documents the `esaa` commands (package `esaa-core`, line 0.5.0b10)
**inside real situations**, not as a list of flags. Each scenario has a goal, the
commands in the order you'd use them, the expected output, and the pitfalls. For
the exhaustive syntax of each subcommand, see the
[CLI reference](esaa-cli-reference.en.md); for the shortest path, the
[Getting started](esaa-getting-started.en.md).

> Conventions: the examples use PowerShell (line continuation with `` ` ``).
> In bash/zsh, swap `` ` `` for `\`. Every command that **writes an event** stamps
> the runner identity — use `--runner <id>` before the subcommand or export
> `ESAA_RUNNER_ID`. The real command is `esaa` (equivalent to `python -m esaa`).

## Personas and authority

Before the scenarios, fix who does what — this explains why certain commands
require a specific `--actor`:

| Persona | Role | What it emits |
|---|---|---|
| **Operator** / Orchestrator | Single writer of the event store | `task create`, `hotfix create`, `issue resolve`, `reject`, `runner metrics`, plugins/roadmaps |
| **agent-spec / agent-impl** | Executing agents | `claim`, `complete`, `issue report` |
| **agent-qa** | Independent reviewer | `review` (the only one that can approve) |

The agent **never** writes directly to `.roadmap/`. It emits intents; the
Orchestrator validates them at the gates (WG-001..005) and persists. Everything
lives in `.roadmap/` and nothing there should be edited by hand.

---

## Scenario index

1. [Bootstrap a workspace from scratch](#scenario-1--bootstrap-a-workspace-from-scratch)
2. [Plan an epic (spec → impl → qa triad)](#scenario-2--plan-an-epic-spec--impl--qa)
3. [Find out what to run now](#scenario-3--find-out-what-to-run-now)
4. [Run the governed cycle by hand](#scenario-4--run-the-governed-cycle-by-hand)
5. [Complete with `edits` instead of `content`](#scenario-5--complete-with-edits-instead-of-content)
6. [Apply an LLM agent envelope (`submit`)](#scenario-6--apply-an-llm-agent-envelope-submit)
7. [Automatic orchestration (`run`)](#scenario-7--automatic-orchestration-run)
8. [Blocked agent: `issue report`](#scenario-8--blocked-agent-issue-report-fail-closed)
9. [Defect in a `done` task: hotfix](#scenario-9--defect-in-a-done-task-the-hotfix-flow)
10. [Reject an invalid output (`reject`)](#scenario-10--reject-an-invalid-output)
11. [Use a roadmap plugin](#scenario-11--use-a-roadmap-plugin)
12. [Create and publish your own plugin](#scenario-12--create-and-publish-your-own-plugin)
13. [Register a runner's capabilities](#scenario-13--register-a-runners-capabilities)
14. [External runner telemetry](#scenario-14--external-runner-telemetry)
15. [Auditing and integrity](#scenario-15--auditing-and-integrity)
16. [Event store maintenance](#scenario-16--event-store-maintenance)
17. [Concurrency and runner identity](#scenario-17--concurrency-and-runner-identity)
18. [Operating real runners: Claude Code, Codex, Gemini CLI, Grok](#scenario-18--operating-real-runners-claude-code-codex-gemini-cli-grok)
19. [Tasks with different runners (heterogeneous workflow)](#scenario-19--tasks-with-different-runners-heterogeneous-workflow)
20. [Why the event store doesn't corrupt under concurrency](#scenario-20--why-the-event-store-doesnt-corrupt-under-concurrency)

At the end there's a [quick command → scenario reference](#quick-reference-command--scenario)
and a [troubleshooting map](#troubleshooting-map).

---

## Scenario 1 — Bootstrap a workspace from scratch

**Situation:** you just installed `esaa-core` and want to turn the project folder
into a governed workspace, with a clean event store and projections.

```powershell
python -m pip install --upgrade --pre esaa-core
python -m esaa --version
# esaa 0.5.0b18 (protocol 0.4.1, esaa 0.4.x)

# Runner identity for the whole session (avoids repeating --runner)
$env:ESAA_RUNNER_ID = "claude-code"

# 1) Install the contracts/schemas/policies packaged in .roadmap/
esaa bootstrap --profile public

# 2) Create the clean canonical state (event store + projections + baseline lessons)
esaa init

# 3) Confirm the projection and event store are consistent
esaa verify
```

What each step does:

- `bootstrap --profile public` materializes `AGENT_CONTRACT.yaml`,
  `ORCHESTRATOR_CONTRACT.yaml`, the schemas, and the policies. Use
  `--profile production` for the hardened variant and `--force` to
  overwrite a previous bootstrap.
- `init` emits the initialization events, creates `.roadmap/activity.jsonl`
  (the historical truth) and reprojects `roadmap.json`, `issues.json`, and
  `lessons.json` — including the reseed of the baseline lessons **LES-0001/2/3**.
  `--run-id` and `--master-correlation-id` correlate this initialization; use
  `--force` only to reinitialize an existing workspace.
- `verify` reprojects from the event store and compares the SHA-256 hash of the
  canonicalized projection. Expected output: `"verify_status": "ok"`. Any
  `mismatch`/`corrupted` makes the CLI exit with code 2.

> **Pitfall:** in a workspace with a strict policy, `init` and any write fail
> with `RUNNER_UNKNOWN` if the runner is not in the registry. Known runners:
> `claude-code`, `claude-cowork`, `codex`, `human-terminal`, `unattended`.

---

## Scenario 2 — Plan an epic (spec → impl → qa)

**Situation:** you're going to deliver an SSO login flow. ESAA models work in
**triads**: a specification task, an implementation task, and a QA task, with
chained dependencies. Whoever creates tasks is the **Orchestrator/operator**.

```powershell
esaa task create T-LOGIN-SPEC --kind spec `
  --title "Especificar fluxo de login" `
  --description "Documentar o fluxo de autenticacao SSO" `
  --output docs/spec/login.md `
  --target documentation

esaa task create T-LOGIN-IMPL --kind impl `
  --title "Implementar fluxo de login" `
  --depends-on T-LOGIN-SPEC `
  --output src/auth/login.php

esaa task create T-LOGIN-QA --kind qa `
  --title "Validar fluxo de login" `
  --depends-on T-LOGIN-IMPL `
  --output docs/qa/login.md
```

The points that decide the outcome:

- `--kind` defines the task's **write boundary**:
  - `spec` → can write to `docs/**`
  - `impl` → `src/**`, `tests/**`
  - `qa` → `docs/qa/**`, `tests/**` (forbidden to touch `src/**`)
- `--depends-on` is repeatable and creates the chain: `IMPL` only becomes
  eligible when `SPEC` reaches `done`, and `QA` after `IMPL`.
- `--output` (repeatable) declares the expected files; `--target` (repeatable)
  is a goal label. `--boundary-grant <fnmatch>` grants an extra write pattern
  **for that task only** (operator authority, T-2070) — for example, a `spec`
  task that also needs to generate a `sql/seed.sql`.
- `--dry-run` simulates the event, validates against the schema, and shows the
  resulting hash **without persisting** — available on almost every transition.
  Use it to review before writing.

---

## Scenario 3 — Find out what to run now

**Situation:** the backlog has dozens of tasks. You want to know, without
guessing, what is unblocked and what can run in parallel.

```powershell
# Everything eligible + parallelizable groups with no write conflict
esaa eligible
```

```jsonc
{
  "last_event_seq": 12,
  "eligible_count": 1,
  "max_parallel": 1,
  "eligible": ["T-LOGIN-SPEC"],
  "parallel_groups": [["T-LOGIN-SPEC"]]
}
```

`T-LOGIN-IMPL` and `T-LOGIN-QA` do **not** appear yet: they depend on tasks that
aren't `done`. To inspect a specific task and learn the **next expected action**
(ends the "is it claim or complete?"):

```powershell
esaa state T-LOGIN-SPEC
# -> status: todo | expected_action: claim

# Minimal package to dispatch the task to an agent
esaa dispatch-context T-LOGIN-SPEC
```

`dispatch-context` returns: the task, `expected_action`, `allowed_actions`, the
envelope schema slice, the applicable active lessons, and — if you registered
capabilities via `input commands` (Scenario 13) — `runtime_capabilities`. It's
exactly what you paste into an LLM runner's prompt.

---

## Scenario 4 — Run the governed cycle by hand

**Situation:** you're going to execute the spec task manually, without an
automatic adapter. The protocol requires **one action per invocation** (LES-0001):
you cannot collapse `claim` + `complete`.

```powershell
# Invocation 1 — claim (todo -> in_progress)
esaa claim T-LOGIN-SPEC --actor agent-spec

# (produce the file content in a file-updates JSON)
#   updates.json:
#   [{ "path": "docs/spec/login.md", "content": "# Login SSO\n..." }]

# Invocation 2 — complete with evidence + files (in_progress -> review)
esaa complete T-LOGIN-SPEC --actor agent-spec `
  --check "docs/spec/login.md cobre os 3 fluxos exigidos" `
  --file-updates updates.json `
  --notes "Especificacao do fluxo de login"

# Invocation 3 — review by independent QA (review -> done | in_progress)
esaa review T-LOGIN-SPEC --actor agent-qa --decision approve
```

Rules the gate enforces:

- **WG-001:** `complete`/`review` require a prior `claim` (`MISSING_CLAIM`).
- **WG-004:** whoever completes must be whoever claimed — `assigned_to == actor`,
  otherwise `LOCK_VIOLATION`.
- `--check` is repeatable and **required**: minimum 1 for `spec`/`impl`/`qa`,
  **2 for hotfix**. It's the verification recorded as evidence.
- `--file-updates` takes a JSON file (or `-` for stdin). Files are applied
  **by the Orchestrator**, with atomic staging in `.roadmap/staging/` —
  the agent never writes the final effect.
- `review` requires an actor with the **QA role** (`review_authorization=qa_role`);
  the author does not self-approve. `--decision request_changes` returns the task
  to `in_progress`; `approve` makes it `done` (terminal and immutable).

> **Tip:** run each step with `--dry-run` first to see the hash and validate the
> envelope before persisting.

---

## Scenario 5 — Complete with `edits` instead of `content`

**Situation:** the `impl` task needs to change a large existing file. Instead of
resending the whole file, you send **surgical edits** anchored to the current
hash — which rejects a patch over an outdated file.

`updates.json`:

```json
[
  {
    "path": "src/esaa/service.py",
    "base_sha256": "0123...def",
    "edits": [
      { "old_string": "texto antigo exato", "new_string": "texto novo", "replace_all": false }
    ]
  }
]
```

```powershell
esaa complete T-LOGIN-IMPL --actor agent-impl `
  --check "login.php implementa o fluxo da spec" `
  --check "tests/auth/login_test.php passa" `
  --file-updates updates.json
```

Semantics that avoid corrupting the file:

- `base_sha256` is the SHA-256 of the file's **current bytes**. If it changed
  since the read → `EDIT_BASE_MISMATCH`.
- `old_string` matches against the UTF-8 text with the file's exact newlines
  (**CRLF included — do not normalize `\r\n` to `\n`**). A non-UTF-8 file →
  `EDIT_INVALID`.
- More than one match requires `replace_all=true`, otherwise `EDIT_AMBIGUOUS`. No
  match → `EDIT_TARGET_NOT_FOUND`.
- The Orchestrator resolves `{path, base_sha256, edits}` to `{path, content}`
  **before** external effects, resource limits, staging, and artifacts. The
  result is identical to the `content` form.

---

## Scenario 6 — Apply an LLM agent envelope (`submit`)

**Situation:** an LLM runner (Codex, Claude Code) produced the full envelope —
`activity_event` + `file_updates` — in JSON. You want to validate and apply it,
passing through all the gates at once.

`output.json` (exactly **one** `activity_event`):

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-LOGIN-SPEC",
    "prior_status": "in_progress",
    "notes": "Especificacao concluida",
    "verification": { "checks": ["spec cobre os 3 fluxos"] }
  },
  "file_updates": [
    { "path": "docs/spec/login.md", "content": "# Login SSO\n..." }
  ]
}
```

```powershell
# Validate without persisting (recommended before applying)
esaa submit output.json --actor agent-spec --dry-run

# Apply for real (or via stdin: cat output.json | esaa submit - --actor agent-spec)
esaa submit output.json --actor agent-spec
```

`submit` is the LLM runners' path: a single envelope, transactional append, all
workflow gates. The rules it enforces:

- Exactly **one** `activity_event` per output (WG-005, `ACTION_COLLAPSE`).
- `file_updates` only with `action=complete` (WG-002, LES-0002).
- `prior_status` always present and consistent with the real state (WG-003,
  `PRIOR_STATUS_MISMATCH`, LES-0003).
- Pure JSON, no markdown or text outside the envelope.

> The agent **never** sends the `runner` field — the Orchestrator stamps it from
> `--runner`/`ESAA_RUNNER_ID`. Operating Codex/Claude Code as runners is detailed
> in [esaa-runners-codex-claude-code.en.md](esaa-runners-codex-claude-code.en.md).

---

## Scenario 7 — Automatic orchestration (`run`)

**Situation:** instead of dispatching task by task, you want ESAA to pull eligible
tasks and execute them via an adapter — mock (tests/CI) or an LLM endpoint.

```powershell
# One step, mock adapter (deterministic, great for CI)
esaa run --steps 1

# Several independent tasks per wave
esaa run --steps 5 --parallel 3

# Run until no eligible task remains
esaa run --until-done

# Against an HTTP LLM endpoint
esaa run --adapter http --llm-url https://my-endpoint/v1 --until-done

# Plan without effects
esaa run --steps 1 --dry-run
```

- `--steps N` limits the waves; `--until-done` ignores `--steps` and runs until
  `eligible` is empty.
- `--parallel N` dispatches up to N tasks **with no write conflict** per wave
  (the `parallel_groups` from Scenario 3).
- `--adapter http` uses `--llm-url`/`--llm-token`/`--llm-timeout` (or the
  `ESAA_LLM_URL` etc. variables). `mock` is the default and makes no network call.

> The `--llm-url` is **not** a generic provider endpoint (OpenAI/Anthropic). It
> must point to a service you build that speaks the ESAA envelope protocol:
> it receives the `dispatch_context` as a `POST` body and returns an
> `agent_result` envelope (`{"activity_event": ...}`) as JSON.

---

## Scenario 8 — Blocked agent: `issue report` (fail-closed)

**Situation:** mid-execution the agent discovers it can't continue — a missing
dependency, insufficient context, an impossible boundary. The correct output is
**not** to force a `complete`; it's to report an issue with evidence.

```powershell
esaa issue report T-LOGIN-SPEC --actor agent-spec `
  --issue-id ISS-LOGIN-SPEC --severity medium `
  --title "Dependencia ausente" `
  --symptom "Nao ha contrato de callback no workspace" `
  --repro-step "Executar esaa dispatch-context T-LOGIN-SPEC" `
  --repro-step "Conferir que nao ha docs/spec/callback.md"
```

- `--severity` ∈ {`low`, `medium`, `high`, `critical`}.
- `--symptom` + `--repro-step` (repeatable) are **required**: the issue must be
  reproducible. Without evidence, there is no issue.
- `issue.report` is the **only** action that accepts `prior_status="done"` — it's
  how you flag a defect on an immutable task (leads to Scenario 9).
- `--fixes T-XXXX` references the defect's target task.

When the Orchestrator/operator addresses the issue:

```powershell
esaa issue resolve --issue-id ISS-LOGIN-SPEC --hotfix-task-id T-LOGIN-HOTFIX
```

---

## Scenario 9 — Defect in a `done` task: the hotfix flow

**Situation:** `T-LOGIN-SPEC` is already `done` (terminal and immutable) and QA
found a gap. `done` **never** reopens. The path is: report the issue → the
Orchestrator creates a **hotfix** (a new task) → run the cycle on the new task.

```powershell
# 1) QA reports the defect pointing at the done task
esaa issue report T-LOGIN-SPEC --actor agent-qa `
  --issue-id ISS-LOGIN-DONE --severity high `
  --title "Spec aprovada deixou lacuna" `
  --symptom "Fluxo de erro nao foi documentado" `
  --repro-step "Comparar spec aprovada com o teste de QA" `
  --fixes T-LOGIN-SPEC

# 2) Orchestrator creates the corrective task (declared scope)
esaa hotfix create --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --scope-patch src/hotfix/

# 3) Run the cycle on the hotfix — complete requires issue_id, fixes, and 2+ checks
esaa claim <HOTFIX-ID> --actor agent-impl
esaa complete <HOTFIX-ID> --actor agent-impl `
  --check "lacuna do fluxo de erro coberta" `
  --check "teste de regressao adicionado" `
  --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --file-updates updates.json
```

Details that matter:

- `hotfix create` generates, in the current core, an `impl` task. `--scope-patch`
  (repeatable) **further restricts** writing but does not change the `task_kind`
  boundary. For a purely documentation fix, prefer creating a new `spec` task
  with `--boundary-grant` when needed.
- The original task stays intact. The hotfix is new work, traceable back to the
  issue.

**Demonstration shortcut:** to see the protocol end to end without assembling
everything by hand, run the ready-made trace:

```powershell
esaa scenario hotfix                 # uses a temporary workspace
esaa scenario hotfix --current       # operates in the current workspace
esaa scenario hotfix --issue-id ISS-DEMO
```

---

## Scenario 10 — Reject an invalid output

**Situation:** an agent sent an envelope that violates a gate (e.g., it collapsed
`claim`+`complete`). The Orchestrator records the rejection with a canonical code —
the history keeps the invalid attempt.

```powershell
esaa reject T-LOGIN-IMPL `
  --error-code ACTION_COLLAPSE `
  --source-action complete `
  --message "Envelope tentou claim e complete na mesma invocacao"
```

The `--error-code` comes from the single source `src/esaa/reject_codes.py`
(`ACTION_COLLAPSE`, `MISSING_CLAIM`, `PRIOR_STATUS_MISMATCH`,
`LOCK_VIOLATION`, `MISSING_VERIFICATION`, ...). To see the canonical vocabulary
of actions and reject codes:

```powershell
esaa vocabulary
esaa vocabulary --profile public
```

---

## Scenario 11 — Use a roadmap plugin

**Situation:** you want to install a pre-packaged set of tasks (e.g., a "security"
roadmap or an SSO client one) instead of creating tasks one by one.
**Installing does not activate** — activation is an explicit step so tasks don't
become runnable by accident.

```powershell
# 1) Discover what exists (bundled and the external catalog at ~/.esaa/plugins)
esaa plugin list --available
esaa plugin list --available --external
esaa plugin list                      # what is already installed in this workspace

# 2) Validate and diagnose before installing
esaa plugin validate security
esaa plugin doctor security           # checks directory, manifest, roadmap, schema, paths

# 3) Install (records in .roadmap/plugins.lock.json — does NOT activate)
esaa plugin install security

# 4) Activate a roadmap execution (now the tasks become eligible)
esaa roadmap activate security --execution-id default

# 5) Track it
esaa roadmap status --detail
esaa eligible
```

The plugin's tasks come in with ids **namespaced** by the execution:

```text
security-default-T-001
```

Control the execution without uninstalling the package:

```powershell
esaa roadmap list --detail
esaa roadmap pause security --execution-id default
esaa roadmap resume security --execution-id default
esaa roadmap deactivate security --execution-id default   # removes from new eligibility
esaa plugin remove security                               # removes the install state
```

Planned-vs-projected view per plugin (how much of the roadmap is off paper):

```powershell
esaa plugin-status --detail
esaa plugin-status --plugin roadmap.sso-client.json   # filters one roadmap file
```

> If you don't provide input on activation, ESAA copies the plugin's example into
> `.roadmap/plugin-inputs/` and validates it against the plugin's input schema. To
> provide your own: `esaa roadmap activate security --input my-input.json`.

---

## Scenario 12 — Create and publish your own plugin

**Situation:** you want to package a reusable roadmap. An ESAA plugin is a
**directory** (not an archive file) with `plugin.json` at the root.

```powershell
# 1) Scaffold a valid starter package
esaa plugin new minha-feature
```

This generates the minimal structure:

```text
minha-feature/
  plugin.json                                   # identity + entrypoints
  roadmap.template.json                         # planned tasks (T-001 spec...)
  inputs/minha-feature.local.example.json       # local input example
  schemas/minha-feature-input.schema.json       # input schema
  README.md
```

`plugin.json` declares the identity and entrypoints (compatible core version,
task-id namespace, capabilities). The `roadmap.template.json` lists the tasks
with simple local ids (`T-001`); ESAA namespaces them at activation
(`minha-feature-default-T-001`).

```powershell
# 2) Edit roadmap.template.json with your tasks, then validate
esaa plugin validate ./minha-feature
esaa plugin doctor ./minha-feature      # check-by-check diagnosis

# 3) Install from the local directory and activate
esaa plugin install ./minha-feature
esaa roadmap activate minha-feature --execution-id default
```

To distribute via the external catalog, place the plugin directory in
`~/.esaa/plugins/` (or point `ESAA_PLUGINS_HOME` at it); it then shows up in
`esaa plugin list --available --external`. See the dedicated guides in
[docs/plugins/](../plugins/authoring.md) (authoring, installing, lifecycle,
security).

---

## Scenario 13 — Register a runner's capabilities

**Situation:** your LLM runner has a specific set of available tools/shells. You
want `dispatch-context` to tell the agent about it, without polluting the
canonical contract.

```powershell
# 1) Validate the capabilities YAML before registering
esaa input commands validate runner-claude-code.yaml

# 2) Register for a runner (writes to .roadmap/runner-inputs/commands/<id>.yaml)
esaa input commands register runner-claude-code.yaml --runner-id claude-code

# 3) Check what is registered
esaa input commands show --runner-id claude-code
```

This input is **local to the workspace**, non-canonical. From the registration on,
it is injected into `dispatch-context` as `runtime_capabilities` (Scenario 3) —
the agent gets to know which shell surfaces/tools it can use.

---

## Scenario 14 — External runner telemetry

**Situation:** an external LLM runner finished a task and you want to record
latency, tokens, and cost as auditable evidence. This is reserved for the
**Orchestrator/operator** — agents do not emit `runner.metrics`.

```powershell
# Via flags
esaa runner metrics `
  --task-id T-LOGIN-IMPL --actor agent-impl `
  --runner-id claude-code --runner-kind llm `
  --model claude-opus-4-8 --command-surface cli `
  --latency-ms 4200 --input-tokens 1800 --output-tokens 950 `
  --cost-estimate 0.12 --status success

# Or via JSON (same fields)
esaa runner metrics --file metrics.json
```

In practice, provide at least `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface`, and `status` (∈ `success`/`failed`/`cancelled`/`unknown`).
It records a `runner.metrics` event. For a structured view of the whole
workspace's runtime:

```powershell
esaa metrics
```

---

## Scenario 15 — Auditing and integrity

**Situation:** you suspect drift (someone hand-edited a projection) or you need to
rebuild the state at a point in history to audit it.

```powershell
# Reproject and compare hash -> ok | mismatch | corrupted
esaa verify

# Also validate the event-store hash chain
esaa verify --chain

# Anchor the hash chain (once; --force only to recreate the anchor explicitly)
esaa chain init

# Force reprojection of the read models from the event store
esaa project

# Rebuild the state up to an event (by numeric seq or event_id)
esaa replay --until 42
esaa replay --until 42 --no-write     # computes without writing the views (auditing)
```

`verify` is the defense against drift: any manual edit to the projections or the
event store is detected by hash, and the CLI exits with code 2 on
`mismatch`/`corrupted`. `replay --no-write` is safe for investigating "how the
state looked at event N" without changing anything.

---

## Scenario 16 — Event store maintenance

**Situation:** `activity.jsonl` grew large, or a file effect was left pending
after a crash, or there are files waiting in an inbox to be processed.

```powershell
# Checkpoint covering events with event_seq <= N (keeps replay auditable)
esaa snapshot --before 100
esaa snapshot --before 100 --compact      # also archives the included events
esaa snapshot --before 100 --compact --dry-run   # shows the plan without writing

# Process pending files from the file-governed inbox
esaa process --dry-run
esaa process

# Recover missing file effects from the forensic artifacts
esaa effects recover --dry-run
esaa effects recover

# Reset the event store (destructive: backs up and truncates)
esaa activity clear --dry-run             # inspects the plan
esaa activity clear --force               # backup in .roadmap/backups/ and clears
esaa activity clear --force --backup-dir .roadmap/backups
```

Cautions:

- `activity clear --force` is destructive. Run `verify` before and after, and
  make sure a single runner is active in the workspace.
- `effects recover` reapplies effects from
  `.roadmap/artifacts/file-effects/` — it's the post-crash recovery of the
  atomic commit. `--dry-run` lists what would be reapplied.
- `snapshot --compact` keeps the event store from growing indefinitely without
  losing replay capability.

---

## Scenario 17 — Concurrency and runner identity

**Situation:** two runners could touch the same workspace. Until robust locks are
validated, the rule is **one runner at a time** per workspace.

```powershell
# Explicit per-command form (precedence: --runner > ESAA_RUNNER_ID > default)
esaa --runner claude-code submit output.json --actor agent-spec

# Per-session form
$env:ESAA_RUNNER_ID = "codex"
esaa task create T-X --kind spec --title "..."
```

Operational discipline:

- Use `--runner <id>` or `ESAA_RUNNER_ID` on `submit`, `task create`, `init`,
  `run`, and other writes. The agent **never** sends the `runner` field; the
  Orchestrator stamps it.
- If `.roadmap/activity.jsonl.lock` exists before you write, **stop and ask**.
- If you hit `STORE_LOCK_TIMEOUT`, `JSONL_INVALID`, or `EVENT_SEQ_*`, stop and
  report.
- After any governed write, run `esaa verify`.
- State is **per workspace**: each folder with `.roadmap/` is an independent
  universe. `--root <path>` chooses which one.

---

## Scenario 18 — Operating real runners: Claude Code, Codex, Gemini CLI, Grok

**Situation:** you want to drive the ESAA cycle using a command-line agent —
Claude Code, Codex (OpenAI), Gemini CLI (Google), or Grok (xAI). The good news:
**ESAA is agnostic to the model and the tool**. There's no MCP, provider plugin,
or SDK. To ESAA, a "runner" is just two things:

1. a **provenance stamp** (`--runner <id>`, G08) recorded on every event;
2. a process that produces the **`agent.result` envelope** in pure JSON and
   submits it via `esaa submit`.

Any LLM CLI that can read a prompt and return JSON works. What changes from tool
to tool is only **where you put the agent contract** (the instruction file each
CLI reads) and **the `runner_id`** you stamp.

### The universal loop (identical for all four)

```powershell
# 1) Pick work and build the agent's context
esaa --runner <id> eligible
esaa --runner <id> dispatch-context T-X      # paste this into the agent's prompt

# 2) The agent answers ONLY the JSON envelope -> save it to envelope.json
#    { "activity_event": {...}, "file_updates": [...] }

# 3) Validate and apply through the gate
esaa --runner <id> submit envelope.json --actor agent-<kind> --dry-run
esaa --runner <id> submit envelope.json --actor agent-<kind>

# 4) Check integrity at the end of each wave
esaa --runner <id> verify
```

Purely deterministic steps (claim, routine review) can use the direct commands
and **spend no tokens**: `esaa --runner <id> claim T-X --actor agent-spec`.

### Per-tool matrix

| Tool | `--runner <id>` | Registered by default? | `runner_kind` | Where to put the agent contract |
|---|---|---|---|---|
| **Claude Code** | `claude-code` | ✅ yes | `llm-agent` | `CLAUDE.md` (or `.claude/CLAUDE.md`) |
| **Codex** (OpenAI) | `codex` | ✅ yes | `llm-agent` | `AGENTS.md` |
| **Gemini CLI** (Google) | `gemini-cli` | ❌ register | `llm-agent` | `GEMINI.md` (and/or `AGENTS.md`) |
| **Grok Build** (xAI) | `grok` | ❌ register | `llm-agent` | `AGENTS.md` (also auto-reads `CLAUDE.md` and `.claude/`) |

This repository already ships `.claude/CLAUDE.md` and `AGENTS.md` — both reflect
`AGENT_CONTRACT.yaml`. **Grok Build** ([x.ai/cli](https://x.ai/cli)) recognizes
both natively (it reads the `AGENTS.md` family and auto-reads `CLAUDE.md` +
`.claude/`), so it picks up the contract with no extra setup. For the **Gemini
CLI**, point the tool at that same contract (a `GEMINI.md` that repeats the rules,
or whatever instruction path the CLI accepts). The golden rule of the contract is
always the same: **one action per invocation, `prior_status` always,
`file_updates` only with `complete`, pure JSON, when in doubt `issue.report`**.

### "Registered by default?" — permissive vs strict

The behavior depends on `runner_validation` in `.roadmap/RUNTIME_POLICY.yaml`:

- **`permissive`** (this workspace's default): **any** `runner_id` is accepted and
  stamped. `gemini-cli` and `grok` work immediately, with no registration.
- **`strict`**: on the `submit` path, a `runner_id` outside the `runners:` section
  of `.roadmap/agents_swarm.yaml` is rejected with `RUNNER_UNKNOWN` **before** the
  workflow gates. (Operator admin commands — `task create`, `init`, `verify` — do
  not require registration.)

To enable Gemini/Grok under strict, **the operator** adds them to the registry
(editing config in `.roadmap/` is an operator action, recorded in the notes):

```yaml
# .roadmap/agents_swarm.yaml  (runners: section)
runners:
  claude-code:   { display_name: "Claude Code (CLI)", kind: "llm-agent" }
  codex:         { display_name: "Codex",              kind: "llm-agent" }
  gemini-cli:    { display_name: "Gemini CLI (Google)", kind: "llm-agent" }
  grok:          { display_name: "Grok (xAI)",          kind: "llm-agent" }
```

### End-to-end example with Gemini CLI

```powershell
$env:ESAA_RUNNER_ID = "gemini-cli"     # provenance stamp

# 1) context
esaa eligible
esaa dispatch-context T-LOGIN-SPEC > ctx.json

# 2) run the agent pointing at the contract (GEMINI.md) and the context
#    -> the CLI must answer ONLY the JSON envelope; save it to envelope.json

# 3) apply and record telemetry
esaa submit envelope.json --actor agent-spec --dry-run
esaa submit envelope.json --actor agent-spec
esaa runner metrics --task-id T-LOGIN-SPEC --actor agent-spec `
  --runner-id gemini-cli --runner-kind llm-agent `
  --command-surface cli --status success
esaa verify
```

Swap `gemini-cli` for `grok`, `codex`, or `claude-code` and **nothing else
changes** in the loop — only the stamp and the instruction file that CLI reads.

> The [Operating Codex and Claude Code as runners](esaa-runners-codex-claude-code.en.md)
> guide details the envelope, the 5 gates, and the dispatch recipes — it applies
> to any of the four tools.

---

## Scenario 19 — Tasks with different runners (heterogeneous workflow)

**Situation:** you want to use the best of each tool in the same workspace — for
example, the spec by Gemini CLI, the implementation by Codex, and the review by
Claude Code. This is **supported and auditable**, because in ESAA the runner is a
**per-event stamp**, and the task lock (WG-004) is by **`actor`** (the agent
identity), **not** by the runner — the runner is never compared between `claim`
and `complete` (`state_machine.py`, `_ensure_owner`).

### A) Heterogeneous per task (sequential hand-off) — the real pattern

This is the most common flow: **one runner owns the task from start to finish**.
One runner active at a time; each task with its own vehicle (the legitimate
exception is *continuation on token exhaustion* — variant B):

```powershell
# spec executed by Gemini CLI
esaa --runner gemini-cli claim    T-LOGIN-SPEC --actor agent-spec
esaa --runner gemini-cli complete T-LOGIN-SPEC --actor agent-spec `
  --check "spec cobre os 3 fluxos" --file-updates spec.json
esaa --runner gemini-cli verify

# impl executed by Codex
esaa --runner codex claim    T-LOGIN-IMPL --actor agent-impl
esaa --runner codex complete T-LOGIN-IMPL --actor agent-impl `
  --check "impl segue a spec" --check "testes passam" --file-updates impl.json
esaa --runner codex verify

# review executed by Claude Code (QA role)
esaa --runner claude-code review T-LOGIN-IMPL --actor agent-qa --decision approve
esaa --runner claude-code verify
```

Each event in `.roadmap/activity.jsonl` carries its own `runner.runner_id` →
full audit of **which vehicle** did **which transition**. Cross-reference it with
per-runner telemetry:

```powershell
esaa --runner codex runner metrics --task-id T-LOGIN-IMPL --actor agent-impl `
  --runner-id codex --runner-kind llm-agent --command-surface cli --status success
esaa metrics
```

**Constant runner, actor changes at review.** In real use (and in this
workspace's history), the `runner` stays the same from `claim` to `done` — what
changes is the **actor** at the review gate. Under the `review_authorization:
qa_role` policy (this workspace's default), whoever completed **cannot**
self-approve unless they already have the QA role: to reach `done`, the `review`
needs an actor with the `qa` (or `orchestrator`) role. So a task's typical path
is:

```text
claim/complete  -> agent-spec | agent-impl | agent-hotfix   (runner X)
review/approve  -> agent-qa                                 (runner X)
```

The runner doesn't change; the actor does, only at the review boundary. If you
want to keep **the actor constant too** from start to finish, run the whole task
with an actor of role QA/orchestrator (e.g., `agent-qa` does claim, complete, and
review) — then `done` is reached without changing identity.

> **Provenance tip:** set `ESAA_RUNNER_ID` per session. If you pass `--runner`
> only on `claim` and forget it on `complete`, the stamp falls back to
> `unattended` (the default) and the task ends up with an inconsistent runner in
> the history — an accidental drift, not a hand-off.

### B) Continuation on token exhaustion (real hand-off)

It does happen: the runner that claimed the task runs out of tokens/context
mid-work, and you ask **another** runner to continue from where the previous one
stopped. ESAA supports this because the lock is by **`actor`**, not by the
runner — the continuing runner just needs to **reuse the same `--actor`** from
the claim:

```powershell
# Runner 1 (Codex) claims and starts
esaa --runner codex claim T-X --actor agent-impl
# ... tokens run out mid-way ...

# Runner 2 (Claude Code) completes — SAME actor, the gate accepts (assigned_to == actor)
esaa --runner claude-code complete T-X --actor agent-impl `
  --check "..." --file-updates updates.json
```

What ends up in the history depends on **which `--runner` you stamp on the
continuation** (the `runner` block is resolved from `ESAA_RUNNER_ID` at the moment
of each invocation, `events.py` → `resolve_runner`):

- **Honest provenance (recommended):** stamp `--runner <continuing-runner>` on the
  events it actually performs. `activity.jsonl` then shows `claim` by `codex` and
  `complete` by `claude-code` — the audit reflects the real hand-off. Optionally,
  `ESAA_ON_BEHALF_OF` records the continuity (e.g., claude-code acting in sequence
  after codex); that field already travels in every event's `runner` block.
- **Inherit the previous id (what usually happens):** if you keep the previous
  runner's `ESAA_RUNNER_ID`, the second runner's work is recorded **under the
  first one's name**. It works — the gate does not check runner continuity — but
  provenance attributes to runner 1 something runner 2 did. It's an auditing
  detail, not a protocol error.

> The etiquette "don't claim a task assigned to another runner" (AGENTS.md §3)
> targets **concurrent sessions** competing for the same task — not this
> sequential, deliberate hand-off where only one runner is active at a time.

### C) Real (concurrent) parallelism — the design allows it, current practice serializes

`esaa eligible` returns `parallel_groups` — tasks with disjoint write boundaries,
logically dispatchable to different runners at the same time:

```powershell
esaa eligible
# parallel_groups: [["T-A","T-B"]]  -> no write conflict
```

Two caveats of operational honesty:

- The current concurrency rule (CLAUDE.md / AGENTS.md §3) is **one runner per
  workspace until robust locks are validated**. Today you parallelize the
  *decision* (the groups tell you what's safe), but you **serialize the writes**.
- `esaa run --parallel N` dispatches N tasks in **a single** orchestrator
  process → all events come out with **the same** runner stamp (`make_event`
  resolves one `ESAA_RUNNER_ID` per process). It's not a multi-runner fan-out.
  True concurrent multi-runner requires **separate sessions**, each with its own
  `--runner` — which the current rule advises against running at the same time.

> **Summary:** different runners on different tasks → yes, freely (sequential).
> Switching runner **mid-task** (continuation on exhaustion) → yes, reusing the
> same `--actor`; just mind the runner stamp. Different runners writing **at the
> same time** in the same workspace → not yet, until robust locks close. The
> barrier is write concurrency, not the provenance model — and **not** integrity:
> see why the store doesn't corrupt in
> [Scenario 20](#scenario-20--why-the-event-store-doesnt-corrupt-under-concurrency).

---

## Scenario 20 — Why the event store doesn't corrupt under concurrency

**Situation:** you're evaluating ESAA critically and want to know whether the
"one runner at a time" rule hides a fragility. What actually happens if two
processes try to write to the same `.roadmap/activity.jsonl`? The short answer:
**integrity is guaranteed by construction; the rule is conservative policy, not a
patch over something broken.** Below, the real mechanism, with the code points.

### 1. The log is sequential by construction

Every governed write only **appends** events to the append-only log — the single
source of truth. Two properties make it intrinsically serial:

- **strictly monotonic `event_seq`**: the next is always `last + 1`
  (`store.py` → `next_event_seq`). There are no two events with the same seq.
- **hash chain**: each event carries `prev_event_hash = previous event_hash`
  (chained in `store.py` → `_prepare_events_for_append`, validated by
  `_validate_hash_chain`). The chain only closes if events are chained
  **in order** — any reordering or later edit breaks verification.

### 2. Writes are serialized by a transactional lock

The write path (`append_transactional`, FIX-1806) runs **the whole** cycle under
an exclusive OS lock:

```text
acquire lock → parse → validate staleness → decide seq → materialize (validate)
            → append → read-after-write → save projections → release lock
```

The lock is born from `os.open(..., O_CREAT | O_EXCL)` — atomic creation of
`.roadmap/activity.jsonl.lock`, with metadata (`pid`, `hostname`, `runner_id`,
`acquired_at`). When **runner B** arrives and **runner A** holds the lock, B
**waits and retries** (50 ms retry); if A doesn't release within the timeout
(30 s on the transactional path), B gets **`STORE_LOCK_TIMEOUT`** and stops. The
two's lines **never interleave** in the file.

### 3. The four layers of defense

| Layer | What it protects | Signal / code |
|---|---|---|
| **Exclusive lock** (`O_EXCL`) | two processes on the write path at once | `STORE_LOCK_TIMEOUT` |
| **Optimistic concurrency** | an append computed over already-outdated state | `STALE_STATE_SEQ` / `STALE_STATE_HASH` |
| **Read-after-write** | what was written is what was meant to be written | `APPEND_VERIFY_FAILED` |
| **Hash chain** | any later break/edit of the log | `EVENT_SEQ_*`, `verify --chain` |

The key piece for the critic is **`STALE_STATE_SEQ`**: even if B acquires the lock
right after A, if the state changed since B built its envelope, the append is
**rejected** instead of applied over stale base. This closes the TOCTOU window
(the gap between "read state" and "write") — the serialization is *correct*, not
merely *mutually exclusive*.

### 4. What it guarantees — and what it doesn't promise

**Guarantees:** there is never write interleaving; there is never an append over
stale state; every write is re-verified by reading; the chain detects later
tampering. On local disk, the event store **does not corrupt** under attempted
concurrent writes.

**Doesn't promise:** (a) parallel *throughput* — writes serialize, so two
concurrent runners gain no speed, only contention; (b) `O_EXCL` atomicity on
**network filesystems** (NFS/SMB), where exclusive-creation semantics and
stale-lock detection (takeover by TTL/live pid) have edge cases; (c) **cross-host**
coordination beyond TTL expiration.

### 5. So why "one runner at a time"?

It's conservative policy for the three reasons above — **not** because the store
is fragile on local disk. The contracts ask for validation **in the target
workspace** (CLAUDE.md / AGENTS.md §3) precisely because the guarantee depends on
the filesystem where `.roadmap/` lives. On local disk the serialization is solid;
on a network, wait for validation before enabling concurrent multi-runner.

### 6. How to audit it yourself

```powershell
esaa verify --chain                 # validates monotonic event_seq + hash chain
esaa replay --until 50 --no-write   # rebuilds the state at event 50 without writing
# inspect the live lock (pid/hostname/runner_id/acquired_at):
Get-Content .roadmap/activity.jsonl.lock
```

> **For the critical reader:** "two runners writing at the same time" in ESAA is,
> in practice, "one writes, the other waits or gets `STORE_LOCK_TIMEOUT`". The
> absence of concurrent multi-runner is a decision of operational caution
> (no throughput gain + filesystem dependency), not a gap in the event store's
> integrity.

---

## Quick reference: command → scenario

| Command | For what | Scenario |
|---|---|---|
| `bootstrap` | install governance templates | 1 |
| `init` | clean canonical state | 1 |
| `verify` / `verify --chain` | check consistency / hash chain | 1, 15 |
| `task create` | create a task (Orchestrator) | 2 |
| `eligible` | what can run now | 3 |
| `state` | status + next action | 3 |
| `dispatch-context` | minimal package for the agent | 3, 13 |
| `claim` | claim (todo→in_progress) | 4 |
| `complete` | complete with evidence + files | 4, 5 |
| `review` | approve/return (QA only) | 4 |
| `submit` | apply agent.result envelope | 6 |
| `run` | automatic orchestration | 7 |
| `issue report` | fail-closed block | 8 |
| `issue resolve` | close an issue | 8 |
| `hotfix create` | fix for a done task | 9 |
| `scenario hotfix` | demonstrable end-to-end trace | 9 |
| `reject` | record an invalid output | 10 |
| `vocabulary` | canonical actions and reject codes | 10 |
| `plugin list/validate/doctor/install/remove` | package lifecycle | 11, 12 |
| `plugin new` | scaffold a plugin | 12 |
| `roadmap activate/status/pause/resume/deactivate/list` | roadmap execution | 11 |
| `plugin-status` | planned vs projected | 11 |
| `input commands validate/register/show` | runner capabilities | 13 |
| `runner metrics` | external runner telemetry | 14 |
| `metrics` | runtime metrics | 14 |
| `chain init` | anchor the hash chain | 15 |
| `project` | reproject read models | 15 |
| `replay` | rebuild state at a point | 15 |
| `snapshot` | checkpoint/compaction | 16 |
| `process` | file-governed inbox | 16 |
| `effects recover` | recover file effects | 16 |
| `activity clear` | reset the event store | 16 |

## Troubleshooting map

| You see | It means | What to do |
|---|---|---|
| `RUNNER_UNKNOWN` | runner outside the registry under a strict policy | use a known runner in `--runner`/`ESAA_RUNNER_ID` (Scenario 1) |
| `MISSING_CLAIM` | `complete`/`review` without a prior `claim` | run `claim` first (Scenario 4) |
| `LOCK_VIOLATION` | whoever completes ≠ whoever claimed | complete with the same `--actor` as the claim |
| `PRIOR_STATUS_MISMATCH` | `prior_status` doesn't match the real one | run `esaa state <id>` and fix it; does not consume an attempt |
| `ACTION_COLLAPSE` | more than one action in the envelope | one action per invocation (Scenario 6) |
| `MISSING_VERIFICATION` | `complete` without `--check` | add checks (1 spec/impl/qa, 2 hotfix) |
| `EDIT_BASE_MISMATCH` | the file changed since `base_sha256` | reread the file and recompute the hash (Scenario 5) |
| `EDIT_AMBIGUOUS` | `old_string` matches several spots | use `replace_all=true` or a more specific snippet |
| `verify_status: mismatch`/`corrupted` | drift in the projection/event store | `esaa project`, investigate with `replay --no-write`, restore a backup |
| `STORE_LOCK_TIMEOUT` / `*.lock` present | another runner in the workspace | stop and ask; one runner at a time (Scenario 17, 20) |
| `STALE_STATE_SEQ` / `STALE_STATE_HASH` | the state changed since the envelope was built | recompose over the current state and resubmit (Scenario 20) |
| `APPEND_VERIFY_FAILED` | read-after-write didn't match what was written | run `verify --chain`; investigate I/O/filesystem (Scenario 20) |

## See also

- [Full CLI reference](esaa-cli-reference.en.md) — syntax of each flag
- [Getting started](esaa-getting-started.en.md) — the shortest path
- [Operating Codex and Claude Code as runners](esaa-runners-codex-claude-code.en.md)
- [Why use ESAA](esaa-why.en.md)
- Plugins: [authoring](../plugins/authoring.md) · [installing](../plugins/installing.md) · [lifecycle](../plugins/lifecycle.md) · [security](../plugins/security.md)
