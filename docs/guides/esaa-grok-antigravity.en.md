# Grok and Antigravity: governed execution with ESAA

🌐 [Português](esaa-grok-antigravity.md) · **English**

## 1. Version and authority

This guide describes the optional verification extension of protocol **0.4.2**. Base storage and projections retain schema 0.4.1. Once verification.configure/run events exist, older runtimes may reject unknown actions; do not downgrade to a reader that does not support this extension. Use a checkout/build containing these interfaces; changing source does not update an earlier global installation.

The operator creates tasks and grants permissions; the Orchestrator alone writes events and final effects. Actor identifies the agent assuming an authorized task role, runner identifies the submitting tool, and model identifies its LLM. Set the real runner with `--runner` or `ESAA_RUNNER_ID`; strict workspaces require registration. Do not attribute a Grok submission to Antigravity. Review follows the workspace policy and authorizations.

## 2. Division of work

Grok selects a task with eligible, obtains dispatch-context and supplies that context plus necessary referenced contents to Antigravity. The auxiliary proposes claim; after acceptance and refreshed context, it prepares the candidate and checks. Each envelope has one action and a matching prior_status. Claim and complete are separate submissions. Submitted envelopes are plain JSON; conversation need not be JSON.

The claimant submits complete. file_updates appears only with complete. Prepare candidates in an allowed area and leave final effects to the Orchestrator. base_sha256 detects a changed edit base; it does not physically prevent tools from writing outside the protocol.

## 3. Interfaces

```text
verification enable --config CONFIG.json [--dry-run]
verification show
verification run TASK-ID --candidate COMPLETE.json --actor ACTOR [--dry-run]
verification result RUN-ID

task create TASK-ID ... [--executable-check ID]...
task amend TASK-ID [--executable-check ID]...
hotfix create --issue-id ISS --fixes TASK-ID [--scope-patch PATH]...
  [--boundary-grant PATTERN]... [--output PATH]... [--executable-check ID]...
task amend TASK-ID [--boundary-grant PATTERN]... | [--clear-boundary-grants]
task amend HOTFIX-ID [--scope-patch PATH]...
complete TASK-ID --actor ACTOR --check TEXT [--execution-id RUN-ID] ...

task list [--status STATUS]... [--kind KIND] [--assigned-to ACTOR]
  [--source event_store|planned|all] [--limit N] [--cursor TOKEN] [--format json|table]
activity list [--task-id ID] [--action ACTION]... [--exclude-action ACTION]...
  [--hide-verify] [--after-seq N] [--limit N] [--format json|jsonl|table]
```

Grants are explicit and never inherited. Replacing grants or scope is allowed only in todo; --clear-boundary-grants conflicts with --boundary-grant. Grants cannot override explicit prohibitions or safe-path validation. Legacy runtime scopes retain external-effect controls; executable verification currently supports regular local files only, without symlinks.

## 4. Catalog and execution

verification enable takes an operator-authorized catalog and records verification.configure; arbitrary commands cannot be supplied by an agent envelope. Activation adds optional schema properties, preserves compatible extensions and rejects conflicts. Dry-run previews without persisting. Do not migrate an existing project through forced bootstrap.

Each check declares id, an image pinned by digest, command as an argument array, and fnmatch inputs. cwd is relative and defaults to a dot. Unknown fields, protected/external paths and unknown IDs are rejected. A task requires the IDs passed through --executable-check.

Defaults: timeout 60 s, 1 CPU, 512 MiB memory, 128 processes, 64 MiB candidate workspace and 1 MiB per log stream. Configurable bounds: timeout 1–3600 s; CPU 1–8; memory 32–8192 MiB; processes 16–1024; workspace 1–1024 MiB; logs 1 KiB–8 MiB. Images must already be local and contain /bin/sh, tar and the check executables. Image preparation is a separate operator action; execution neither pulls images nor installs dependencies.

Only authorized inputs and candidate content enter private tmpfs. Containers receive no host mounts, network, inherited host credentials or Docker socket. The root filesystem is read-only; processes use UID 65534, no capabilities and no-new-privileges. There is no local-process fallback. Operators must select trusted images and input patterns excluding secrets.

Results record checks, images, exit codes, duration, timeout/cancellation, hashes and bounded logs. verification result checks result and log integrity. Runner provenance remains in the Orchestrator event.

## 5. Delivery binding and failures

Copy the approved run_id into activity_event.verification.execution_id; the complete shortcut also accepts --execution-id. The gate compares task, actor, cycle, active configuration, inputs and normalized candidate content. Input changes during execution produce stale results. Every catalog activation invalidates previous evidence, even for equivalent configuration. request_changes starts another cycle requiring a new execution.

Complete validates initially and under lock, including adapters. A batch cannot modify inputs of another verified delivery. Complete does not execute tests. Neither dry-run, verify nor replay executes checks. Missing Docker, a nonlocal image, timeout, cancellation, altered logs or missing evidence cannot authorize applying a candidate.

Declarative checks remain compatible for tasks without executable_checks; minimum counts remain one for common tasks and two for hotfix. Execution evidence does not replace requirement evaluation, visual inspection or QA. If failure occurs after append but before effects finish, stop and follow effect diagnosis/recovery; do not edit events or projections.

## 6. Reproducible synthetic demonstration

This example creates a synthetic tetris.py in a fresh workspace. Its sole requirement is containing the fixed marker. It demonstrates the flow without testing Pygame, gameplay, accessibility or the original Tetris. The pinned Alpine image must already be local. For the actual game, configure an image and real logic, rendering and interaction checks appropriate to the task.

```bash
set -e
esaa_demo_root="$(mktemp -d -t esaa-grok-demo-XXXXXX)"
esaa_demo_candidate="$(mktemp -t esaa-candidate-XXXXXX.json)"
esaa_demo_result="$(mktemp -t esaa-result-XXXXXX.json)"
esaa_demo_config="$(mktemp -t esaa-checks-XXXXXX.json)"
export ESAA_RUNNER_ID=grok-bot
python -m esaa --root "$esaa_demo_root" bootstrap --profile public
python -m esaa --root "$esaa_demo_root" init
python -m esaa --root "$esaa_demo_root" chain init
cat > "$esaa_demo_config" <<'JSON'
{"checks":[{"id":"marker","image":"alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce","command":["/bin/sh","-c","grep -q fixed tetris.py"],"inputs":["tetris.py"]}]}
JSON
python -m esaa --root "$esaa_demo_root" verification enable --config "$esaa_demo_config" --dry-run
python -m esaa --root "$esaa_demo_root" verification enable --config "$esaa_demo_config"
python -m esaa --root "$esaa_demo_root" task create T-DEMO --kind impl \
  --title "Synthetic candidate marker" --output tetris.py \
  --boundary-grant tetris.py --executable-check marker
python -m esaa --root "$esaa_demo_root" dispatch-context T-DEMO
python -m esaa --root "$esaa_demo_root" claim T-DEMO --actor agent-impl
python -m esaa --root "$esaa_demo_root" dispatch-context T-DEMO
cat > "$esaa_demo_candidate" <<'JSON'
{"activity_event":{"action":"complete","task_id":"T-DEMO","prior_status":"in_progress","verification":{"checks":["Synthetic marker checked in Docker"]}},"file_updates":[{"path":"tetris.py","content":"# fixed\n"}]}
JSON
python -m esaa --root "$esaa_demo_root" verification run T-DEMO \
  --candidate "$esaa_demo_candidate" --actor agent-impl > "$esaa_demo_result"
python - "$esaa_demo_candidate" "$esaa_demo_result" <<'PY'
import json,sys
from pathlib import Path
candidate=Path(sys.argv[1]); payload=json.loads(candidate.read_text())
result=json.loads(Path(sys.argv[2]).read_text())
assert result['status']=='passed'
payload['activity_event']['verification']['execution_id']=result['run_id']
candidate.write_text(json.dumps(payload))
PY
python -m esaa --root "$esaa_demo_root" submit --actor agent-impl --dry-run "$esaa_demo_candidate"
python -m esaa --root "$esaa_demo_root" submit --actor agent-impl "$esaa_demo_candidate"
python -m esaa --root "$esaa_demo_root" review T-DEMO --actor agent-qa --decision approve
python -m esaa --root "$esaa_demo_root" task list --status done --format table
python -m esaa --root "$esaa_demo_root" activity list --hide-verify --format table
python -m esaa --root "$esaa_demo_root" verify
python -m esaa --root "$esaa_demo_root" verify --chain
```

## 7. Hotfix, queries and metrics

For a defect after done, report an issue without --fixes and explicitly create its hotfix with scope, outputs, grants and required checks. Alternatively, issue report --fixes automatically creates a default hotfix: do not create it again. Amend a hotfix only while todo; the original task stays done. Approving a linked hotfix may resolve its issue automatically.

task list combines event-store and plugin-planned tasks; planning is not execution evidence. Repeated statuses use OR; different dimensions are combined. Ordering is by task_id; cursors bind filters, sources and observed sequence. QUERY_CURSOR_STALE asks clients to restart after state changes. Default/maximum limits are 100/1000.

activity list orders by event_seq. Include/exclude action filters apply, with exclusion winning. --task-id matches the payload task_id without transitive issue/original-task associations. --hide-verify changes output only. Resume at next_after_seq; JSON also includes observed sequence and has_more. Uninitialized workspaces fail without creating directories. Table and JSONL are presentation formats, not store mutations.

attempts_total counts output.rejected. --runner records provenance; tokens and latency require observed runner metrics. Do not invent unavailable measurements. Verify checks projection consistency; an anchored chain additionally checks hashes without proving functionality or retroactively authenticating an unanchored past.

## References

- [Getting started](esaa-getting-started.en.md)
- [CLI reference](esaa-cli-reference.en.md)
- [Scenarios](esaa-cenarios.en.md)
