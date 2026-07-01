# ESAA — Getting started

🌐 [Português](esaa-getting-started.md) · **English**

A practical guide: from zero to the first full `todo → in_progress → review →
done` cycle in an ESAA-governed workspace.

## 1. Installation

```powershell
pip install esaa-core
esaa --version   # e.g.: esaa 0.5.0b10 (protocol 0.4.1, esaa 0.4.x)
```

The package installs the `esaa` command (equivalent to `python -m esaa`). There
is no server, daemon, or MCP: everything is a local CLI + files in the project
directory.

## 2. Create the workspace

At the project root:

```powershell
$env:ESAA_RUNNER_ID = "codex"      # or use --runner codex on each command
esaa bootstrap --profile public     # contracts, schemas, and minimal guides
esaa init                           # clean canonical state (event store + projections)
```

- `bootstrap --profile public` installs the packaged governance templates
  (`AGENT_CONTRACT.yaml`, `ORCHESTRATOR_CONTRACT.yaml`, schemas, policies).
  `--profile production` installs the hardened variant. Use `--force` to
  overwrite a previous bootstrap.
- `esaa init` emits the initialization events and creates `.roadmap/activity.jsonl`
  (the source of truth) and the projections `roadmap.json`, `issues.json`,
  `lessons.json` — including the reseed of the baseline lessons LES-0001/2/3.

Everything ESAA governs lives in `.roadmap/`. **Never edit those files by
hand** — every mutation goes through the Orchestrator.

### Global flags

Every command accepts:

- `--root <path>` — workspace root (default: current directory). State is
  **per workspace**: each folder with `.roadmap/` is an independent universe.
- `--runner <id>` — runner identity stamped on every event (G08), e.g.:
  `--runner codex`, `--runner claude-code`. May come from `ESAA_RUNNER_ID`.
  In workspaces with a strict policy, commands that write events fail without a
  registered runner.

## 3. Create tasks

```powershell
esaa task create T-LOGIN-SPEC --kind spec `
  --title "Especificar fluxo de login" `
  --description "Documentar o fluxo de autenticacao SSO" `
  --output docs/spec/login.md --target documentation

esaa task create T-LOGIN-IMPL --kind impl `
  --title "Implementar fluxo de login" `
  --depends-on T-LOGIN-SPEC `
  --output src/auth/login.php

esaa task create T-LOGIN-QA --kind qa `
  --title "Validar fluxo de login" `
  --depends-on T-LOGIN-IMPL `
  --output docs/qa/login.md
```

Optional G07 fields describe operational intent and acceptance contract without
changing the `kind` boundary:

```powershell
esaa task create T-GOV-SPEC --kind spec `
  --task-type governance `
  --title "Specify typed review contract" `
  --output docs/spec/review-contract.md `
  --acceptance-criterion "The spec defines required_review_mode" `
  --acceptance-criterion "The spec defines validation before append" `
  --required-review-mode governance `
  --supersedes T-OLD-SPEC
```

- `--kind` defines the write **boundaries**: `spec` → `docs/**`;
  `impl` → `src/**`, `tests/**`; `qa` → `docs/qa/**`, `tests/**` (`src/**` forbidden).
- `--task-type` describes intent (`feature`, `hotfix`, `audit`, `release`,
  `memory`, `governance`, `maintenance`); `--kind` still decides actor and
  boundary.
- `--boundary-grant <fnmatch>` grants an extra write pattern for that task only
  (operator authority, T-2070).
- `--dry-run` simulates the event and shows the resulting hash without persisting —
  available on practically every transition.

## 4. Discover what is runnable

```powershell
esaa eligible
```

Returns the tasks runnable now (dependencies satisfied) and the
`parallel_groups` — groups that can run in parallel without conflict.

For a specific task:

```powershell
esaa state T-LOGIN-SPEC              # status + next expected action
esaa dispatch-context T-LOGIN-SPEC   # minimal context to dispatch to an agent
```

## 5. The governed cycle (two-step)

The protocol requires **one action per invocation** (LES-0001). The minimal cycle:

```powershell
# Invocation 1 — claim (todo → in_progress)
esaa claim T-LOGIN-SPEC --actor agent-spec

# Invocation 2 — complete with evidence and files (in_progress → review)
esaa complete T-LOGIN-SPEC --actor agent-spec `
  --check "docs/spec/login.md cobre os 3 fluxos exigidos" `
  --file-updates updates.json `
  --notes "Especificacao do fluxo de login"

# Invocation 3 — review by independent QA (review → done | in_progress)
esaa review T-LOGIN-SPEC --actor agent-qa --decision approve
```

Critical points:

- `--file-updates` takes a **JSON file** (or `-` for stdin) with an array
  `[{"path": "...", "content": "..."}]` — or the compact `edits` form with
  `base_sha256`, which rejects a patch over an outdated file. Files are applied
  **by the Orchestrator**, with atomic staging in `.roadmap/staging/`.
- `--check` is repeatable and required: minimum 1 for `spec`/`impl`/`qa`,
  2 for hotfix.
- `review` requires an actor with the **QA role** (`review_authorization=qa_role`);
  whoever completes cannot self-approve. `--decision request_changes` returns the
  task to `in_progress`.
- If the task defines `required_review_mode`, `review` must provide a matching
  `--review-mode`; missing, invalid, or mismatched modes fail before append to
  `activity.jsonl`.
- Whoever completes must be whoever claimed (`assigned_to == actor`), otherwise
  `LOCK_VIOLATION`.

### Automatic execution

```powershell
esaa run --steps 3                 # runs N steps with the mock adapter
esaa run --adapter http --llm-url https://... --until-done
```

`run` dispatches eligible tasks to an adapter (mock for tests, HTTP for an LLM
endpoint), with `--parallel N` per wave. For interactive runners
(Codex/Claude Code), see the [runners guide](esaa-runners-codex-claude-code.en.md).

## 6. Verify integrity

```powershell
esaa verify           # reprojects and compares hash → ok | mismatch | corrupted
esaa verify --chain   # also validates the event-store hash chain
esaa project          # forces reprojection of the read models
esaa replay --until 42 --no-write   # state at any point in history
```

`verify` is the defense against drift: any manual edit to the projections or the
event store is detected by hash.

## 7. When something goes wrong

```powershell
# Blocked during execution → issue with evidence
esaa issue report T-LOGIN-SPEC --actor agent-spec `
  --issue-id ISS-LOGIN-SPEC --severity medium `
  --title "Dependencia ausente" `
  --symptom "Nao ha contrato de callback no workspace" `
  --repro-step "Executar esaa dispatch-context T-LOGIN-SPEC"

# Defect in a done task (immutable) → hotfix, never reopen
esaa issue report T-LOGIN-SPEC --actor agent-qa `
  --issue-id ISS-LOGIN-DONE --severity high `
  --title "Spec aprovada deixou lacuna" `
  --symptom "Fluxo de erro nao foi documentado" `
  --repro-step "Comparar spec com teste de QA" `
  --fixes T-LOGIN-SPEC
esaa hotfix create --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --scope-patch src/hotfix/

# Invalid agent output → explicit rejection recorded
esaa reject T-X --error-code ACTION_COLLAPSE --source-action complete --message "..."
```

See the end-to-end demonstration: `esaa scenario hotfix`.

## 8. Maintenance

```powershell
esaa snapshot --before 100 --compact   # checkpoint + auditable compaction
esaa activity clear --dry-run          # check the cleanup plan
esaa activity clear --force            # backup and reset the event store
esaa metrics                           # structured runtime metrics
```

## Read next

- [Practical scenarios (cookbook)](esaa-cenarios.en.md) — each command inside a real situation
- [Full CLI reference](esaa-cli-reference.en.md)
- [Operating Codex and Claude Code as runners](esaa-runners-codex-claude-code.en.md)
- [Why use ESAA](esaa-why.en.md)
