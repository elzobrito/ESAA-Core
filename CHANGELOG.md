# Changelog

## Unreleased

- Added: `esaa plugin-status` CLI command. Cross-references each
  `.roadmap/roadmap*.json` plugin against the live projection and reports
  per-plugin task counts plus optional task-level detail. Read-only; never
  mutates state. See `docs/operations/plugin-status.md`.

## 0.5.0b1 - Public Beta

- Added packaged ESAA governance templates for public workspaces.
- Added `esaa bootstrap` with `public` and `production` profiles.
- Added public release metadata, MIT license, contribution docs, quickstart, examples, CI, and release workflow.
- Kept ESAA protocol/schema version at `0.4.1` while preparing the Python package beta as `0.5.0b1`.
- Documented production operation, external runners, and package smoke-test flow.
