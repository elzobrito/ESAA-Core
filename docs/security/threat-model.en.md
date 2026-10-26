# Threat model — ESAA identity and file effects

🌐 [Português](threat-model.md) · **English**

## Status and scope

Candidate 0.5.0b22, protocol 0.4.2, storage 0.4.1. Independent identity review is pending: **BLOCKED_EVIDENCE**. This document describes the design and observed tests without certifying production security. See the [upgrade guide](../guides/esaa-upgrade-0.5.0b22.en.md) and [evidence](../qa/closeout-20261026/hotfix-review-input.md).

## Assets and authorities

Protected assets are history, projections, task ownership, review authorization, boundaries and final file-effect bytes. The Orchestrator validates and writes; runner records operational provenance and does not substitute for cryptographic identity. In legacy mode actor names follow local policy but do not prove key possession. Ed25519 authentication is an explicitly activated extension; historical HMAC/identity.strict examples do not describe this protocol.

The owner controls bootstrap authority, external pin and host enrollment. Agents control proposals and candidates and should not control these external records or owner keys. The Orchestrator process, operating system, cryptographic implementation and authorized configuration form the trusted base.

## Threat controls and evidence

| Threat | Candidate control | Limit/evidence |
|---|---|---|
| Invalid credentials discarded in inactive registry | Non-null authorization requires bootstrap; None preserves legacy | Implementer tests; final review pending |
| Alias enables self-review or identity collision | Canonical principal for ownership/review; reverse actor/alias collision rejected | API/CLI/replay tests; final review pending |
| Project rollback or lost/replaced ESAA_TRUST_ROOT | Public enrollment discovered from OS profile; external root/fingerprint bound to workspace | Requires real owner isolation; final review pending |
| Rewritten history with recalculated chain | v2 pin commits the full history prefix in addition to projections | Unanchored chain alone is insufficient; final review pending |
| Concurrent checkpoint regression | Read/validate/write under record lock; store → pin order | Deterministic concurrency test; final review pending |
| Activation crash before checkpoint | Durable intent before first append, bound to planned events | Interruption fails closed; owner handles recovery |
| Bytes swapped between verification and application | Commit builds a fresh temporary file from validated in-memory content; unique names, atomic replace, preserved mode | Independent review repeated tampering/concurrency and passed |
| Changed candidate reuses execution | Executable evidence binds task/actor/cycle/configuration/inputs/candidate | Optional isolated Docker; textual declarations are not execution |

Signatures, sequence and replay rules are validated before effects are accepted. Store locking coordinates writers and grants no extra authorization. Never remove locks manually. Integrity failures require stopping and diagnosis rather than log editing.

## Boundaries and non-guarantees

`ESAA_TRUST_ROOT` alone is not independent trust. Unix enrollment uses the OS home resolved by UID; Windows uses OS-profile LocalAppData. HOME/XDG do not select this registry. Enrollment and trust root must both remain outside the workspace and deny agent writes. An agent on the same UID may retain access despite mode 0700. Host, owner or trusted-process compromise is not solved by this design.

There is no automatic v1-to-v2 pin conversion, automatic bootstrap or permission to reconstruct trust solely from the project-controlled replica. Tests use disposable fixtures; no real bootstrap was performed in this work. Core's unanchored chain and the executable extension being disabled by default do not imply activation: these are optional states that must be reported accurately.

Local policy controls review authorization; a QA name/alias and a passing test do not replace independent review. The historical scanner covers only its snapshot. Complementary review of final identity bytes remains incomplete; the release gate stays closed.
