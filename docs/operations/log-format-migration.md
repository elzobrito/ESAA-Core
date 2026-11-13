# Log Format Migration (`schema_version` `0.4.1` -> `0.4.2`, inline `projection_hash_after`)

## Summary of Change (`AUD-O2-070`)
- New events emitted by `make_event` carry `schema_version: "0.4.2"` (upcasted from `"0.3.0" -> "0.4.0" -> "0.4.1" -> "0.4.2"` by `esaa.compat.upcast_event`).
- Write batches (`init`, `submit`, `process`, `orchestrator_commit`, `activity clear`) no longer append automatic `verify.start` and `verify.ok` pairs. Instead, the last event of each committed batch carries two optional envelope fields:
  - `projection_hash_after`: SHA-256 of the materialized `roadmap.json` projection after applying the batch.
  - `projector_version`: `PROJECTOR_VERSION` (`"1"`) that computed `projection_hash_after`.
- Historical `verify.start`, `verify.ok`, and `verify.fail` events remain in `CANONICAL_ACTIONS` and continue to replay cleanly in mixed logs.

## Backward Compatibility (Older Binaries Reading `0.4.2` Logs)
Tested empirically against `v0.5.0b29` (`git worktree` isolated checkout) reading a `0.4.2` store created by `esaa init --with-demo-tasks`:
- **Pre-upcaster-chain releases (`<= 0.5.0b29`):** `parse_event_store` does not reject unknown `schema_version` values and ignores `projection_hash_after` / `projector_version`. `esaa verify` exited `0` (`verify_status: "ok"`) without validating `projection_hash_after`, and any write from `<= 0.5.0b29` would emit `0.4.1` with `verify.start`/`verify.ok`.
- **Upcaster-chain releases without the `0.4.2` route:** `upcast_event` fails closed with `CorruptedStoreError` (`UNSUPPORTED_EVENT_SCHEMA_VERSION`).

## Upgrade Procedure
1. Upgrade `esaa-core` across all runners and operator terminals before writing new events to a `0.4.2` store.
2. Run `esaa --root <workspace> verify --full` to validate all `projection_hash_after` checkpoints at the current `PROJECTOR_VERSION`.
3. Do not rewrite or strip historical `verify.start` / `verify.ok` events from existing `activity.jsonl` logs; mixed logs (`0.4.1` + `0.4.2`) are supported natively.
