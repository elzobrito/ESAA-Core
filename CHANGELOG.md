## 0.5.0b21

Hotfix beta for legacy event stores.

- Replay/projection again accepts historical hotfix `scope_patch` entries that 0.5.0b19 accepted (for example absolute paths), so `esaa verify` no longer fails with `HOTFIX_SCOPE_INVALID` on existing stores (ISS-ESAA-B21-LEGACY-ABS-SCOPE / HF-ISS-ESAA-B21-LEGACY-ABS-SCOPE).
- New commands (`hotfix create`, `task amend --scope-patch`, `issue report`, `submit`) still reject absolute or otherwise unsafe scopes.
- `esaa verify` reports such historical entries under `warnings` with code `LEGACY_SCOPE_PATCH_UNSAFE`; the projection hash and schema are unchanged.
- Regression tests cover legacy replay (verify ok + warning) and strict rejection in create/amend.
- Users of 0.5.0b20 with legacy absolute scopes should upgrade directly to 0.5.0b21.

## 0.5.0b20

Beta announcing protocol 0.4.2 with an optional executable verification extension; storage stays on schema 0.4.1.

- `verification enable/show/run/result`: operator-authorized checks in isolated Docker (digest-pinned images, no network, no host mounts, no local fallback).
- `--executable-check` on `task create`, `task amend` and `hotfix create`; completion requires a passed `verification.execution_id` bound to task, actor, cycle, configuration, inputs and candidate.
- `hotfix create` accepts `--boundary-grant`, `--output` and `--executable-check`; `task amend` supports grants and `--scope-patch` while in `todo`.
- `task list` and `activity list` queries with filters, pagination and table/jsonl formats.
- Optional actor registry with signed history; hash-chain anchor generated under lock.
- Upgrade guides: `docs/guides/esaa-upgrade-0.5.0b20.md` (PT) and `.en.md` (EN).
- Known issue: stricter hotfix scope validation also ran on replay and broke `verify` on stores with legacy absolute `scope_patch`; fixed in 0.5.0b21.

## 0.5.0b19

Beta refresh with concise, task-specific agent guidance and portable consumer documentation.

- Root guides route to the relevant contracts and operational references instead of repeating them.
- Five PARCER profiles retain their roles and identities while defining objectives, evidence and completion.
- Local reversible choices and recoverable context are distinguished from material decisions and contractual blockers.
- Consumer README, AGENTS and CLAUDE files work without the Core documentation tree; bootstrap modes and protocol gates are preserved.
- Distribution tests cover local links, project-content preservation, bilingual examples and semantic contract parity.
- Restored the missing historical hotfix resolution link through an appended Orchestrator event, preserving the original event history and the evidence audit test.

## 0.5.0b17

Local beta with empty-by-default `init` and optional demo seeds.

Highlights:

- `esaa init` no longer creates demo tasks `T-1000`/`T-1010`/`T-1020` by default (empty task list + baseline lessons).
- Added `init --with-demo-tasks` (API: `with_demo_tasks=True`) to opt into the historical demo track.
- Plugin roadmap seeds still take precedence over demo seeds.
- Init result includes `task_source` (`empty`/`demo`/`plugin`), `tasks_seeded`, and `with_demo_tasks`.
- Formalized via INIT-EMPTY-001 / INIT-EMPTY-010 / INIT-EMPTY-020.
- Built local package artifacts `esaa_core-0.5.0b17` (sdist + wheel).

## 0.5.0b16

Local beta refresh for Mira-style guided onboarding.

Highlights:

- Simplified `esaa onboard` so the interactive flow asks only how agents should address the operator.
- Added `operator.display_name` to the governed project profile and `dispatch-context`.
- Kept technical profile fields inferred from the workspace by default instead of requiring manual answers.
- Preserved compatibility with older project profile projections that do not yet include `operator`.
- Validated `onboard --answers {"operator_name": "Elzo"} --dry-run` against ESAA-Core-GUI without mutating its event store.
- Built local package artifacts `esaa_core-0.5.0b16` (sdist + wheel).

## 0.5.0b15

Public beta with guided project onboarding and governed project profile.

Highlights:

- Added `esaa onboard` (interactive, `--answers`, `--dry-run`) and `esaa profile show`.
- Added reserved event `project.profile.set` and projection `.roadmap/project_profile.json`.
- Packaged schema `project_profile.schema.json` (bootstrap + package templates).
- Onboarding creates governance track `GOV-PROFILE-001/010/020` and can supersede seed tasks.
- `eligible`/`run` hide `superseded_by` tasks and report `suppressed_superseded*`.
- Compact `project_profile` summary injected into `dispatch-context`.
- Validation fixture: dry-run against ESAA-Core-GUI without mutating its event store.
- Formalized via ONBOARD-001 / ONBOARD-010 / ONBOARD-020.
- Built local package artifacts `esaa_core-0.5.0b15` (sdist + wheel).

# Changelog

## 0.5.0b14

Version bump and packaging refresh (0.5.0b14).

- Updated single-source `PACKAGE_VERSION` to 0.5.0b14.
- Refreshed install examples and current package references in documentation.
- Built new `esaa_core-0.5.0b14` sdist + wheel.

## 0.5.0b13

Public beta refresh for spoken transition notifications.

Highlights:

- Replaced Linux sample-audio fallback with spoken messages via available speech backends.
- Added `--notify-transition` for `claim`, `complete`, and `review` to speak the resulting transition.
- Kept `--notify-completion` as a compatibility shortcut for speaking `Task done`.
- Published package `esaa-core 0.5.0b13` on PyPI.

## 0.5.0b12

Public beta build refresh for state-machine separation cleanup.

Highlights:

- Removed completion-notification semantics from the canonical state machine.
- Kept the optional completion alarm as an opt-in service/CLI side effect after `review approve -> done`.
- Updated README release guidance for `0.5.0b12`.
- Prepared local package build artifacts for `esaa-core 0.5.0b12`.

## 0.5.0b11

Public beta refresh for terminal completion notifications.

Highlights:

- Added optional local completion alarm support for `review approve -> done`.
- Added `review --notify-completion` and `ESAA_NOTIFY_ON_DONE=1` opt-in controls.
- Added regression coverage for terminal completion detection and CLI notification triggering.
- Published package `esaa-core 0.5.0b11` on PyPI.

## 0.5.0b10

Public beta refresh for safer bootstrap behavior in existing workspaces.

Highlights:

- Added `bootstrap --preserve-guides` to install or refresh ESAA governance
  without overwriting existing `AGENTS.md`, `.claude/CLAUDE.md`, or `README.md`.
- Added `bootstrap --merge-guides` to compose packaged ESAA guidance with
  project-local guide content using deterministic marker regions.
- Added bootstrap merge reject codes for conflicting flags and malformed guide
  marker regions.
- Promoted packaged `AGENTS.md` and `CLAUDE.md` from minimal stubs to practical
  operational ESAA contracts.

## 0.5.0b9

Public beta refresh for runner-local command capability input.

Highlights:

- Added `python -m esaa input commands validate/register/show` for local runner
  command capability YAML files.
- Injected registered command capabilities into `dispatch-context` as
  `runtime_capabilities`.
- Published package `esaa-core 0.5.0b9` on PyPI.

## 0.5.0b8

Public beta refresh focused on lower token overhead and stricter file update
semantics.

Highlights:

- Added compact `file_updates.edits` with `base_sha256`,
  `old_string`/`new_string`, and structured edit rejection codes.
- Rejected duplicate effective file update paths with
  `FILE_UPDATE_DUPLICATE_PATH`.
- Added `boundary_grant` support for explicit temporary task write grants.
- Reduced dispatch context and operational guidance payloads to lower repeated
  runner context load.
- Split the previous `service.py` monolith into smaller runtime modules while
  keeping `service.py` as a facade.
- Added regression coverage for edit encoding, duplicate updates, dispatch
  context order, and service decomposition.
- Published package `esaa-core 0.5.0b8` on PyPI.

## 0.5.0b1

Public beta preparation for `esaa-core`.

This release focuses on the local ESAA runtime, deterministic verification,
installable roadmap plugins, bundled plugin examples, external runner metrics,
hotfix flow, snapshots, and publication-ready package assets.
