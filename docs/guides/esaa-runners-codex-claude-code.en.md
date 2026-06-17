# Operating Codex and Claude Code as ESAA runners

🌐 [Português](esaa-runners-codex-claude-code.md) · **English**

ESAA does not use MCP. LLM runners (Codex, Claude Code, Antigravity, etc.)
integrate via **local CLI + files**: they read the context the Orchestrator
exposes, produce an `agent.result` envelope, and submit it to the gate. This
guide shows the full flow and the rules that avoid rejection.

## Roles

- **Runner** — the software that runs the LLM (Codex CLI, Claude Code). It stamps
  provenance (`--runner`) and telemetry (`runner metrics`).
- **Agent** — the logical identity that signs the transitions (`--actor`), e.g.:
  `agent-spec`, `agent-impl`, `agent-qa`. A runner may operate several agents,
  but **whoever completes must be whoever claimed** (WG-004).
- **Orchestrator** — the `esaa` CLI: the single writer of the event store, it
  validates everything before persisting.

## 1. Runner identity (provenance, G08)

Every command that writes an event must stamp who is executing:

```powershell
esaa --root <workspace> --runner codex <subcommand> ...
esaa --root <workspace> --runner claude-code <subcommand> ...
# or once per session:
$env:ESAA_RUNNER_ID = "codex"
```

The identity is recorded on every event — an audit of *who* did *what*.
In the examples below, if `ESAA_RUNNER_ID` is not set, keep
`--runner <id>` on every command that persists events.

## 2. Register environment capabilities (`input commands`)

Solves the classic problem "the agent doesn't know whether it can use PowerShell,
WSL, grep, sed". Once **per workspace**:

```powershell
esaa --root <workspace> --runner codex input commands register `
  docs/operations/runtime-capabilities.windows-wsl.yaml
esaa --root <workspace> --runner codex input commands show
```

The YAML declares `command_surfaces` (powershell, cmd, wsl_ubuntu, ...),
`available_tools`, tools verified in WSL, and
`recommended_agent_rules`. It lives in
`.roadmap/runner-inputs/commands/<runner-id>.yaml` — **local to the workspace**
(not global to the installation) and non-canonical (it does not enter the event
store). The content is injected into `dispatch-context` as
`runtime_capabilities`.

## 3. Get the minimal task context

```powershell
esaa eligible                        # what can run now
esaa dispatch-context T-EXEMPLO      # dispatch package for one task
```

`dispatch-context` brings everything the agent's prompt needs — and nothing more:

- `task` (id, kind, status, description, outputs, depends_on)
- `expected_action` and `allowed_actions` (e.g.: `claim` + `issue.report`)
- `schema_slice` — the slice of `agent_result.schema.json` valid right now
- active `lessons` applicable to the kind (inviolable constraints)
- `runtime_capabilities` (if registered)

## 4. The two-step cycle

**One action per invocation** (LES-0001, gate WG-005). The runner invokes the
agent twice per task:

### Invocation 1 — claim (signaling, no technical work)

Via envelope:

```json
{"activity_event": {"action": "claim", "task_id": "T-EXEMPLO", "prior_status": "todo"}}
```

```powershell
esaa --runner claude-code submit claim.json --actor agent-spec
```

Or via the deterministic shortcut (without spending an LLM call):

```powershell
esaa --runner claude-code claim T-EXEMPLO --actor agent-spec
```

### Invocation 2 — complete (work + evidence + files)

The agent produces the full envelope:

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-EXEMPLO",
    "prior_status": "in_progress",
    "notes": "resumo do que foi produzido",
    "verification": {"checks": ["criterio 1 atendido", "criterio 2 atendido"]}
  },
  "file_updates": [
    {"path": "docs/spec/exemplo.md", "content": "<conteudo completo>"}
  ]
}
```

```powershell
esaa --runner claude-code submit complete.json --actor agent-spec
```

Envelope rules (schema `additionalProperties: false`):

- **Pure JSON** — no markdown, no fences, no loose text.
- `prior_status` required and equal to the injected status (WG-003).
- Fields like `event_seq`, `ts`, `actor`, `assigned_to` are **forbidden** —
  the Orchestrator generates them.
- `file_updates` only with `action=complete` (WG-002); paths within the
  `task_kind` boundaries (`spec`→`docs/**`; `impl`→`src/**`,`tests/**`;
  `qa`→`docs/qa/**`,`tests/**`).
- Compact form: `file_updates.edits` with `base_sha256` — a small patch that
  fails if the base file changed (saves tokens and avoids blind overwrites).
- Files are applied by the **Orchestrator** with atomic staging; the agent never
  writes directly to the repository.

### Invocation 3 — review by independent QA

```powershell
esaa --runner claude-code review T-EXEMPLO --actor agent-qa --decision approve
```

`review_authorization=qa_role`: the owner does not self-approve
(`REVIEW_ROLE_VIOLATION`). `request_changes` returns the task to
`in_progress`.

### When blocked: `issue.report`

Fail-closed — if a dependency, context, or boundary is missing, the agent emits:

```json
{
  "activity_event": {
    "action": "issue.report",
    "task_id": "T-EXEMPLO",
    "prior_status": "in_progress",
    "issue_id": "ISS-0001",
    "severity": "high",
    "title": "Dependencia X nao esta done",
    "evidence": {"symptom": "...", "repro_steps": ["passo 1", "passo 2"]}
  }
}
```

## 5. The 5 workflow gates (why outputs are rejected)

| Gate | Checks | Reject code |
|---|---|---|
| WG-001 | `complete`/`review` only after `claim` | `MISSING_CLAIM` |
| WG-002 | `complete` requires checks; `file_updates` requires `complete` | `MISSING_VERIFICATION` / `MISSING_COMPLETE` |
| WG-003 | `prior_status` matches the roadmap | `PRIOR_STATUS_MISMATCH` |
| WG-004 | Whoever completes is whoever claimed | `LOCK_VIOLATION` |
| WG-005 | One action per output | `ACTION_COLLAPSE` |

`PRIOR_STATUS_MISMATCH` is the only rejection that does **not** consume an attempt
(treated as context lag). Limits: 3 attempts per task, a 2-min cooldown, and a
30-min TTL per attempt.

## 6. Runner telemetry

After each external execution, the operator/harness records evidence:

```powershell
esaa --runner codex runner metrics `
  --task-id T-EXEMPLO `
  --actor agent-spec `
  --runner-id codex `
  --runner-kind codex `
  --model gpt-5 `
  --command-surface "powershell: python -m esaa submit" `
  --latency-ms 1250 `
  --input-tokens 4200 `
  --output-tokens 900 `
  --status success `
  --correlation-id CID-T-EXEMPLO
```

It becomes a `runner.metrics` event (reserved for the Orchestrator — agents never
emit it), giving real telemetry without depending on the model provider. Required
fields: `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface`, and `status`.

## 7. Practical recipes

### Codex / Claude Code as an interactive operator

1. `esaa --runner codex eligible` → pick a task.
2. `esaa --runner codex dispatch-context T-X` → build the agent's prompt.
3. The agent answers **only the JSON envelope** → save it to a file.
4. `esaa --runner codex submit envelope.json --actor agent-<kind>` (use
   `--dry-run` first if you want to validate without persisting).
5. Repeat for the complete; dispatch `agent-qa` for the review.
6. `esaa --runner codex verify` at the end of each wave.

### Deterministic transitions without an LLM

For steps that need no reasoning (claim, routine review, task create), use the
direct commands (`claim`, `review`, `task create`) — zero tokens.

### Recommended system instruction for the agent

The project's `CLAUDE.md`/`AGENTS.md` file should reflect
`AGENT_CONTRACT.yaml`: one action per invocation, `prior_status` always
present, `file_updates` only with complete, never touch `done`, when in doubt
`issue.report`. In case of divergence, the canonical artifacts in `.roadmap/`
prevail.

## See also

- [Getting started](esaa-getting-started.en.md)
- [CLI reference](esaa-cli-reference.en.md)
- [Why use ESAA](esaa-why.en.md)
