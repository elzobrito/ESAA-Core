# ESAA upgrade — 0.5.0b22 candidate

🌐 [Português](esaa-upgrade-0.5.0b22.md) · **English**

Status on 2026-10-26: **candidate under review; publication blocked**. Protocol 0.4.2, storage 0.4.1. Local source reports b22; this machine's operational installations were aligned to public b21. b22 has neither been published nor installed operationally. Do not perform the upgrade below before approval and confirmed publication.

## Message for Grok and Antigravity

ESAA is a local event-based governance protocol. Its package is `esaa-core`, its module is `esaa`; there is no ESAA MCP server. Agents propose results; the Orchestrator validates contracts, records events and applies effects. `.roadmap/activity.jsonl` is authoritative. Projections are rebuilt and must never be patched manually.

Grok may coordinate while Antigravity executes a bounded task. Record the actual executor as runner; actor identifies the authorized identity/role, not the model name. Changing models transfers neither ownership nor permissions.

1. Inspect `python -m esaa --root /path/project eligible` and local contracts.
2. Create self-contained tasks before implementation: context, dependencies, outputs, boundaries and acceptance criteria. Use installed-version help for command syntax.
3. Give the assistant `dispatch-context TASK-ID` and retrieve necessary references. The entire backlog is no substitute for task context.
4. Submit `claim` and `complete` separately. The claiming actor completes; final effects belong in `file_updates` with complete. Identify the real runner on every write.
5. Request review from the authorized role. Review precedes done; done is terminal. Later defects require issue/hotfix.
6. Run `verify` after governed writes. Structural integrity, tests, review and publication are separate evidence.

## Reported gaps and current behavior

- **Root-level files:** `scope_patch` restricts paths; it grants no writes. `hotfix create` supports `--boundary-grant`, `--output` and `--executable-check`. Explicitly authorize a required file such as `tetris.py` according to the contract; do not move files to evade boundaries.
- **Duplicate hotfix:** `issue report --fixes` already creates a hotfix. Choose that flow or report the issue and create a hotfix separately. Do not combine both for the same link.
- **Verify events:** verification event pairs are part of the history of write commands. Their log proportion alone proves neither waste nor a defect. Preserve history and query with `activity list`.
- **Complete checks:** textual checks remain declarations. The optional executable-verification extension executes checks in isolated Docker when enabled/configured by the operator. It does not automatically execute text. Evidence binds candidate, task, actor and cycle; changes invalidate reuse.
- **Listing:** use `task list` and filter/pagination help. `eligible` lists available tasks rather than the entire backlog.
- **Chain and metrics:** inspect `chain --help` before initializing a chain; a valid chain without an external anchor has limited guarantees. Use `runner metrics`; `attempts_total` counts rejections, not every execution.

b21 preserves replay of historical absolute scopes and warns with `LEGACY_SCOPE_PATCH_UNSAFE`; new writes still reject unsafe scopes. Avoid b20 for affected stores. b22 adds typing, staging, alias and identity protections described in the [threat model](../security/threat-model.en.md). Final identity bytes still require independent review.

## Upgrade after release

First confirm approval of the exact commit, CI and a PyPI publication with matching hashes. Preserve a workspace copy and the owner's external records. Update each environment actually using ESAA without accidentally mixing installations:

```bash
# Only after confirmed b22 publication:
python -m pip install --upgrade 'esaa-core==0.5.0b22'
# For a pipx-managed installation:
pipx upgrade esaa-core
python -m esaa --version
esaa --version
python -m esaa --root /path/project verify
```

Use a virtual environment or pipx with system-managed Python; do not override system protection. `pipx upgrade` follows its original spec: confirm it resolved exactly b22. Compare user Python, the PATH executable and pipx's environment. Smoke-test an isolated workspace first. Local wheel/sdist evidence is provisional and does not establish PyPI publication.

## Identity activation belongs to the owner

An upgrade must not bootstrap identity, create permanent keys or automatically activate identity. Legacy mode does not establish cryptographic identity. Once activated, protected operations require Ed25519 signatures and canonical-identity rules; aliases of one principal are not independent reviewers.

The candidate uses an `esaa.identity.trust.v2` pin, full-history commitment, serialized checkpoint and durable activation intent before the first append. Public enrollment is discovered from the operating-system user profile, outside the workspace, independently of HOME/XDG and `ESAA_TRUST_ROOT`. The trust-root location must match that enrollment. The owner must deny agents write access to these records: mode 0700 with an agent on the same UID does not establish isolation.

The owner prepares a pin through the `make_pin(public_key_hex=...)` API, keeps private keys outside artifacts and prepares signed authorizations according to the contract. CLI commands include `actor trust-import --pin FILE`, `actor bootstrap --authorization FILE --dry-run`, `actor register`, `actor bind-alias`, and `--authorization` for protected operations. There is no `trust-pin template` command. Inspect help and satisfy the preactivation gate before real activation.

A v1 pin is not automatically converted to v2. Migration requires an owner decision and trusted reference. Do not delete enrollment/checkpoint or reconstruct trust from the project replica to overcome failure. Do not downgrade after identity/alias events or a v2 pin without a validated compatibility/recovery plan. Interrupted bootstrap must remain blocked for owner recovery.

## Evidence and resumption

The implementer's suite passed 597 tests; staging and packaging received specific independent reviews. This does not complete identity review. The historical scanner retains its snapshot; complementary review cannot be attributed to that scan. See the [blocker report](../qa/closeout-20261026/hotfix-review-input.md) and [distribution evidence](../qa/actor-registration/packaging/README.md).

Automatic safety review blocked continuation of the identity auditor for possible cybersecurity risk. Scanner artifact storage also still rejects persistence. There is therefore no READY_FOR_OWNER_BOOTSTRAP, b22 release or activation authorization. Resume through permitted independent review, resolved coverage/storage, QA004 and release gates. No PyPI token was read during this preparation.
