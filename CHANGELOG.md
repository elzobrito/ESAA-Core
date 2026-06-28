# Changelog

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
