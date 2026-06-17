# Threat Model - ESAA Identity

🌐 [Português](threat-model.md) · **English**

> Scope: G03 / SEC-02
> Goal: define what ESAA assumes as trusted and which attacks the actor/runner model must block.

## Protected assets

- Integrity of the event store `.roadmap/activity.jsonl`.
- State derived from tasks (`roadmap.json`, `issues.json`, `lessons.json`).
- Per-`task_kind` write boundaries.
- Review authority and the transition to `done`.
- File effects applied by the Orchestrator.

## Trust boundaries

Trusted:

- Orchestrator/ESAA CLI running locally.
- The event store file lock while it remains intact.
- `agents_swarm.yaml` and `RUNTIME_POLICY.yaml` versioned in the workspace.
- Actor secrets when provided via environment/keyfile outside the event store.

Not trusted on their own:

- The `actor` string received in a command or automation payload.
- A name with the `agent-qa*` prefix.
- The envelope content produced by an agent.
- Plugin input, including external roots and runtime paths.
- HTTP/LLM adapter responses.

## Threats covered by G03

1. **Escalation via actor name:** a caller uses `agent-qa-fake` to obtain the QA role by prefix. Mitigation: strict actor registry, no prefix fallback.
2. **Unauthorized review:** the actor who claimed tries to approve their own delivery without the QA role. Mitigation: `review_authorization=qa_role` + role resolved in the swarm.
3. **Complete by a third party:** a different actor tries to complete a claimed task. Mitigation: WG-004 with `assigned_to` derived from the claim.
4. **Use of a registered actor without credentials:** a caller knows the `agent-qa` name and tries to use it. Optional mitigation: `identity.auth.mode=hmac` with `ACTOR_AUTH_FAILED`.
5. **Secret persistence:** a token shows up in the event log or projection. Mitigation: the token is a command input only, never a persisted payload.

## Threats out of immediate scope

- Local user with direct write permission to `.roadmap/activity.jsonl`; handled by the G02 hash chain and by filesystem controls.
- Orphan lock/concurrency on append; handled by G04.
- Plugin pointing to an arbitrary directory; handled by G05.
- Full compromise of the local host; requires controls external to ESAA.

## Resulting guarantees

With `identity.strict=true` and `review_authorization=qa_role`:

- Role is always an explicit authorization from the swarm.
- A name prefix grants no privilege.
- Review approve only comes from an authorized QA/orchestrator.
- Complete still respects the claim's ownership.
- Identity failures happen before schema/gates/effects, staying fail-closed.
