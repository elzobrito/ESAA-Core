# Changelog

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
