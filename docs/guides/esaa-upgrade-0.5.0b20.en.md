# Upgrading to esaa-core 0.5.0b20

🌐 [Português](esaa-upgrade-0.5.0b20.md) · **English**

## 1. What changes

0.5.0b20 announces protocol **0.4.2**, which adds an **optional** executable verification extension. Storage and projections remain on schema **0.4.1**; a project that does not enable the extension keeps working as on 0.5.0b19. Check with:

```bash
esaa --version
# esaa 0.5.0b20 (protocol 0.4.2, storage protocol 0.4.1, esaa 0.4.x)
```

Relevant changes for Grok, Antigravity and other runners:

- `verification enable/show/run/result`: an operator-authorized check catalog executed in isolated Docker, with digest-pinned images, no network, no host mounts and no local fallback.
- `--executable-check ID` on `task create`, `task amend` and `hotfix create`; completing such tasks requires `verification.execution_id` (or `complete --execution-id RUN-ID`) from a passed result bound to task, actor, cycle, configuration, inputs and candidate.
- `hotfix create` with `--boundary-grant`, `--output` and `--executable-check`; `task amend` with grants (`--boundary-grant`, `--clear-boundary-grants`) and `--scope-patch`, allowed only in `todo`.
- Queries: `task list` (filters, cursor pagination, `--format table`) and `activity list` (action filters, `--hide-verify`, `--after-seq`, `json|jsonl|table` formats).
- Actor registry and identity with signed history (`esaa actor ...`), optional and preserved on legacy replay.
- Hash-chain anchor generated under lock and projected in the same transaction.
- Python APIs `create_task`, `create_hotfix` and `amend_task` keep their positional arguments; new parameters are keyword-only.

## 2. Before upgrading: backup

The event store is the source of truth. Copy `.roadmap/` (or commit it) before upgrading and confirm the current state:

```bash
esaa verify
esaa verify --chain        # if the chain is anchored
cp -a .roadmap ".roadmap.bak-$(date +%Y%m%d%H%M%S)"
```

## 3. Upgrade

```bash
python -m pip install --user --upgrade --pre esaa-core==0.5.0b20
esaa --version
esaa verify
```

Use the same Python/CLI the runner already uses; updating a checkout's source does not update a global install, and vice versa. For isolated environments, install into a venv and call `python -m esaa`.

Do not run `bootstrap --force` to migrate an existing project: it is unnecessary and may overwrite customized contracts. The new templates only matter for projects created from scratch.

## 4. Enabling executable verification (optional)

1. Prepare a trusted, digest-pinned image locally containing `/bin/sh`, `tar` and the check executables (the executor never pulls images).
2. Write the catalog and enable it, dry-run first:

```bash
esaa verification enable --config checks.json --dry-run
esaa verification enable --config checks.json
esaa verification show
```

3. Mark tasks: `esaa task amend T-ID --executable-check unit` (task in `todo`).
4. Runner flow: `claim` → prepare the complete candidate → `esaa verification run T-ID --candidate complete.json --actor agent-impl` → copy the passed `run_id` into `activity_event.verification.execution_id` → `submit` (dry-run, then real) → `review`.

The full walkthrough and a reproducible synthetic demo are in [Grok and Antigravity](esaa-grok-antigravity.en.md).

## 5. Migration limits and compatibility

- **No downgrade after enabling.** Once `verification.configure`/`verification.run` are recorded, runtimes older than 0.5.0b20 may reject those actions on replay. Keep every reader of the project on b20 or later.
- Re-enabling the catalog invalidates earlier evidence; `request_changes` starts a new cycle and requires a new run.
- Tasks without `executable_checks` still accept declarative checks (minimum 1; hotfix, 2).
- Grants are explicit, never inherited, and do not override prohibitions or safe-path. Grants/scope change only in `todo`; status never goes back.
- `complete`, `verify`, dry-run and replay never run checks. Missing Docker, a non-local image, timeout or missing evidence block completion of configured tasks.
- Executable evidence does not replace requirement evaluation, visual inspection or QA.
- Never hand-edit events or projections; on failure, use an issue and a hotfix.

## 6. For Grok

- Identify as the runner: `--runner grok-bot` or `ESAA_RUNNER_ID=grok-bot`.
- One task at a time: `eligible` → `dispatch-context` → `claim` → `complete` → `review`; `claim` and `complete` are separate submissions.
- Read state only through the CLI: `task list`, `state`, `activity list --hide-verify`, `verify`.
- When delegating to a helper (e.g. Antigravity), hand over the `dispatch-context` and review everything returned; the submission is recorded with the real runner.
