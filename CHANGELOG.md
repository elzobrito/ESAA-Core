## 0.5.0b28

- Read governance schemas and affected test fixtures explicitly as UTF-8, avoiding Windows CP1252 decoding failures.
- `activity clear` preserves the exact original bytes in its backup and computes the recorded byte count and SHA-256 from those bytes, including LF and CRLF histories.
- Unsupported binary staging returns the registered `BINARY_PLATFORM_UNSUPPORTED` JSON error. Binary staging still requires secure POSIX dirfd support; positive integration tests are scoped accordingly and rejection tests remain cross-platform.
- CI audits runtime dependencies from `pyproject.toml` with `pip-audit --strict .`, so a source release does not need to exist on PyPI before its dependency audit can run. Linux/Windows test matrices and existing quality gates remain enabled.
- Local validation of the reviewed hotfix: 921 tests passed, 5 skipped, 88.67% coverage. Protocol and storage versions, active identity policy and opt-in runner separation are unchanged.

## 0.5.0b27

- Top-level `esaa --help` now includes an agent workflow: read the workspace AGENTS.md, retrieve dispatch-context, follow the local contract and lessons, identify the actual runner, and submit claim and complete separately.
- The help reminds agents that the Orchestrator applies effects and that the event store and projections must not be edited directly. Command syntax and read-only help behavior are unchanged.

## 0.5.0b26

Beta release of audit Waves 0 and 1.

Governance hardening from the 2026-11-10 technical audit (`docs/audit/ESAA-CORE-AUDIT-2026-11-10.md`). Protocol and storage versions are unchanged.

- `claim` is rejected while any `depends_on` task is not `done` (`DEPENDENCY_NOT_DONE`) or when the task has `superseded_by` (`TASK_SUPERSEDED`). The rule applies at admission; historical claims keep replaying.
- New optional policy key `review_runner_separation` (default `off`). With `enforce`, in legacy `qa_role` review mode, the runner that performed the current `claim` or `complete` of a task cannot review it (`SELF_REVIEW_FORBIDDEN`).
- Lessons reported by agents through `issue.report` start as `proposed` and stay out of the dispatch context until the operator decides. New commands `esaa lesson list|approve|reject`; the decision is an `orchestrator.view.mutate` event (`change: lesson_status`). Lessons recorded by earlier versions keep replaying as `active`. The packaged `lessons.schema.json` accepts the `proposed` status.
- With `runner_validation: strict`, operator commands (`task create`, `task amend`, `task set-limits`, `reject`, `issue resolve`, `hotfix create`, `activity clear`, lesson decisions) require a runner registered with `kind: human` (`OPERATOR_REQUIRED`). `permissive` (default) is unchanged.
- `activity clear` records the previous log SHA-256, event count and backup path in the first event of the new log.
- `actor=orchestrator` is rejected for every agent action submitted through `submit` (`ORCHESTRATOR_IMPERSONATION`).
- File effects are confined to the resolved workspace root, or to the authorized external target root. Destinations that resolve outside it, pass through a non-directory component, or target a symlink or directory are rejected with `BOUNDARY_VIOLATION` before staging, artifacts or events.
- `verify` compares the content of `roadmap.json`, `issues.json` and `lessons.json` with the event-store replay and reports `mismatch` with a `divergent` list; unreadable projections are reported as mismatch instead of raising.
- Upgrade note: a workspace whose projections were written by an earlier version in a different shape may report `mismatch` until `esaa project` rebuilds them.
- Governance property tests (`tests/test_governance_properties.py`) with evidence in `docs/qa/AUD-O0-governance.md`.

- Replay uses indexed task lookup and avoids repeated materialization; the 50,000-event acceptance benchmark completes locally with verify around 2 seconds and claim around 3 seconds.
- Event appends and projection replacements flush file data; atomic replacement protects individual projections. Multi-file recovery remains replay-based. `store repair` can quarantine one malformed final JSONL line.
- `verify` reports hash-chain status; `init --with-chain` enables opt-in chaining. Timestamp regressions are reported without redefining event ordering.
- Input and workspace failures produce one JSON stderr line; `ESAA_DEBUG=1` enables tracebacks. Read commands do not create an event store in uninitialized directories.
- Administrative writes and submission rejection accounting validate the locked event prefix. `task release --reason` recovers stalled claims and resets attempt limits; `eligible` lists stale claims.
- Runtime policy rejects unsupported keys and invalid values. Reserved settings remain explicitly documented.
- CI checks all source and tests with Ruff and Black, blocks on mypy, enforces a measured coverage baseline of 88.07%, audits dependencies, and includes Linux/Windows Python 3.11–3.13 jobs.
- Known limitation: binary staging requires POSIX secure dirfd support; some binary-input tests still expect success on Windows. Adding the Windows matrix does not establish Windows compatibility. Identity and stronger runner separation remain opt-in.

## 0.5.0b25

Beta that keeps the packaged policy ceilings historical. Recommended install over 0.5.0b23 and 0.5.0b24.

- Packaged `RUNTIME_POLICY.yaml` ships without `resource_limit_caps`, so new workspaces keep the 32 updates / 2 MiB per update / 8 MiB total ceilings.
- The `resource_limit_caps` in the ESAA-Core repository's own `.roadmap/RUNTIME_POLICY.yaml` remain an intentional workspace divergence from the packaged template.
- Supersedes 0.5.0b24. Publication evidence: `docs/qa/core-binary-release-20261102.md`.

## 0.5.0b24

Intermediate beta, superseded by 0.5.0b25.

- Added `resource_limit_caps` to the packaged `RUNTIME_POLICY.yaml` to match the live workspace policy.
- Known issue: the packaged caps changed the default administrative ceiling and a policy regression test failed in CI; reverted in 0.5.0b25.

## 0.5.0b23

Beta with binary file effects and per-task resource limits. Superseded by 0.5.0b25.

- Binary `file_updates` variant (`source`, `size`, `sha256`) applied by the Orchestrator; `esaa input binary` stages the input for a claimed task.
- Per-task `resource_limits` through `--max-file-bytes`, `--max-total-bytes` and `--max-file-updates` on `task create` and `task amend`; optional `resource_limit_caps` policy ceilings.
- `task set-limits`: audited `task.limits.set` event for an `in_progress` task, with `--reason` and `--authorized-by`.
- `contract migrate` and `contract revert`: selective migration of the active schemas without `bootstrap --force`.
- New reject codes `RESOURCE_LIMIT_INVALID`, `LIMITS_CHANGE_BLOCKED`, `CONTRACT_MIGRATE_CONFLICT` and `CONTRACT_MIGRATE_INVALID`.
- Known issue: the packaged `RUNTIME_POLICY.yaml` did not match the live policy and the template parity test failed in CI.

## 0.5.0b22

Beta with external trust pin, canonical actor principal, and preactivation evidence.

- Protocol remains 0.4.2; storage remains 0.4.1. Publication does not activate identity; owner bootstrap stays a separate step.
- Correct explicit typing in identity-history scope reconstruction without relaxing validation.
- Apply validated in-memory file content with unique temporary names; preserve existing file mode and prevent mutable staging bytes from changing the verified candidate.
- Reject non-null authorization in inactive identity registries and reverse actor/alias collisions.
- Trust pin schema `esaa.identity.trust.v2`: OS-profile owner enrollment, full-history commitments, serialized checkpoints and durable pre-append activation intent. Pin v1 is not automatically migrated.
- Closeout 26/10/2026: identity hotfixes 002/003 and signed-replay postfix reviewed via `qa_role`; complementary security audit recorded; QA-PREACTIVATION-004 complete as NO-GO_SECURITY for owner bootstrap; residual open issues remain BOOTSTRAP-AUTHORITY (owner), SCAN-STORAGE (BLOCKED_STORAGE) and CLOSE-INDEPENDENT-REVIEW.
- Add regression coverage for identity/trust, clean wheel/sdist smoke evidence and bilingual upgrade/threat-model documentation.

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
