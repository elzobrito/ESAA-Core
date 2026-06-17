# Why use ESAA

🌐 [Português](esaa-why.md) · **English**

> **ESAA — Event Sourcing for Autonomous Agents.** A governance architecture and
> event-sourced protocol for autonomous agents (Codex, Claude Code, scripts,
> humans) to work on the same project without "magic" state, without invisible
> history, and without one agent running over another.

## The problem

Coding agents (LLMs) are good at producing artifacts and bad at operational
discipline. Without governance, a typical multi-agent flow suffers from:

- **Magic state** — files change with no record of who changed them, when, or why.
- **Invisible history** — decisions made in the middle of a prompt are lost.
- **Step collapse** — the agent "gets ahead" of the work: it claims, executes,
  and approves everything in a single response, with no checkpoint.
- **State drift** — the status file says one thing, the repository says another.
- **Invisible rework** — the same mistake is repeated because nothing records the lesson.

## The solution in one sentence

> Every state advance is an **immutable event** validated by a **single writer**
> (the Orchestrator); agents only **emit intents**, and any readable state is a
> **deterministic projection** of the event store — verifiable by replay and hash.

## Features and the problems they solve

### State and auditing

- **Event store**: records everything in `.roadmap/activity.jsonl`, with a
  monotonic `event_seq`. Solves invisible history, lost decisions, and "magic"
  state.
- **Read models**: project `roadmap.json`, `issues.json`, and `lessons.json` for
  fast reads without editing the source of truth.
- **`verify` / `replay`**: recompute projections from the event store. They catch
  drift, corruption, manual edits, and inconsistency between log and projection.
- **Snapshots/compaction (`snapshot`)**: create auditable checkpoints so the
  event store can grow without losing replay capability.

### Governed workflow

- **Orchestrator**: validates and applies transitions as the single writer. It
  prevents the agent from writing state directly or breaking protocol.
- **State machine**: controls `todo → in_progress → review → done`. Avoids
  skipping steps, completing without a claim, or reopening a `done` task.
- **Workflow gates (WG-001..005)**: block invalid outputs before persisting, such
  as a collapsed claim+complete, wrong status, missing verification, or a
  violated lock.
- **Boundaries**: limit writes per `task_kind` (`spec`, `impl`, `qa`). They keep
  a documentation task from changing code or QA from touching `src/**`.
- **Governed `file_updates`**: applies files only via `complete`, with atomic
  staging. Removes loose mutations without an event, evidence, or validation.
- **`file_updates.edits`**: sends small patches with `base_sha256`. Reduces
  payload and avoids overwriting an outdated file.

### Dispatch and runners

- **`eligible`**: computes the next runnable tasks and parallel groups. Avoids
  picking a blocked or dependent task, or one outside safe parallelism.
- **`state`**: shows a task's deterministic status and the next expected action.
  The agent doesn't have to guess whether to emit a claim or a complete.
- **`dispatch-context`**: delivers minimal per-task context, including status,
  expected action, schema slice, lessons, and runtime capabilities.
- **Runtime capabilities (`input commands`)**: registers, per runner, the
  available surfaces and tools. Solves the "can I use PowerShell, WSL, grep, or
  sed in this workspace?" problem.
- **Runner provenance (`--runner`)**: stamps the runner identity on every event.
  Provides an audit of who executed each transition.
- **Runner metrics (`runner metrics`)**: records tokens, latency, model, status,
  and command surface. Provides real telemetry without depending on the provider.

### Exceptions, recovery, and extension

- **`reject`**: records `output.rejected` with a canonical code. A protocol error
  leaves a trail instead of becoming loose chatter.
- **Issues**: record blockers and failures with `symptom` + `repro_steps`.
- **Lessons**: inject learnings as active constraints on every invocation.
- **Hotfix workflow**: a defect in a `done` task becomes `issue.report` + hotfix
  or a new corrective task; the original task stays immutable.
- **`process` (inbox)**: processes pending files from `.roadmap/inbox/` as a
  file-governed channel.
- **`scenario`**: runs deterministic scenarios, such as the hotfix trace, to
  validate the protocol end to end.
- **`vocabulary`**: shows canonical mappings of actions, reject codes, and
  profiles, so each runner doesn't invent its own language.
- **External plugins and roadmaps**: `plugin`, `plugin-status`, and `roadmap`
  install, validate, and activate task packages without mixing the domain into
  the core.
- **Bootstrap and PyPI package**: `bootstrap` creates standardized workspaces;
  `pip install esaa-core` makes `esaa` / `python -m esaa` available outside the
  local checkout.
- **No-token CLI**: `claim`, `complete`, `review`, `task create`, and other
  deterministic commands avoid spending an LLM call on mechanical transitions.

## Operational security principles

- **Fail-closed**: when in doubt, the agent emits `issue.report` — it never
  improvises.
- **Locks and attempts**: at most 3 attempts per task, a 2-min cooldown, and a
  30-min TTL per attempt (`RUNTIME_POLICY.yaml`).
- **`done` is immutable**: a defect in a completed task generates a hotfix, never
  a reopening.
- **Explicit rejections**: every invalid output becomes `output.rejected` with a
  canonical code (single source: `src/esaa/reject_codes.py`).
- **No MCP**: integration is via local CLI and files — auditable and deterministic.

## Read next

- [Getting started guide](esaa-getting-started.en.md)
- [CLI reference](esaa-cli-reference.en.md)
- [Operating Codex and Claude Code as runners](esaa-runners-codex-claude-code.en.md)
