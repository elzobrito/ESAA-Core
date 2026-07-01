# QA G07 Task Lessons Review Model

## Scope

Validated the G07 implementation against `docs/spec/G07-task-lessons-review-model.md`.

This QA covered:

- backward-compatible optional task fields;
- `task_type`, `acceptance_criteria`, `required_review_mode`, `supersedes`;
- derived `superseded_by` projection;
- typed review validation for `approve` and `request_changes`;
- invalid review inputs failing before append to `activity.jsonl`;
- dispatch-context exposure for G07 task fields;
- lessons status, scope filtering, and enforcement shape;
- legacy lesson shape compatibility;
- documentation updates in CLI reference and getting started guides.

## Evidence

Commands run:

```text
PYTHONPATH=src python -m pytest -q /tmp/esaa-g07-qa/tests/test_g07_end_to_end.py
```

Result:

```text
2 passed in 0.64s
```

```text
PYTHONPATH=src python -m pytest -q tests/test_g07_schema_contracts.py tests/test_g07_task_model.py tests/test_g07_review_mode.py tests/test_g07_lessons_dispatch.py /tmp/esaa-g07-qa/tests/test_g07_end_to_end.py
```

Result:

```text
19 passed in 1.74s
```

## End-to-End Coverage

`tests/test_g07_end_to_end.py` adds two flow-level tests:

- a CLI/service workflow that creates a G07 task with optional fields, claims it,
  checks dispatch-context, completes it, verifies missing and mismatched
  `review_mode` do not append events, requests changes with the required mode,
  completes again, and approves with the required mode;
- a replay/context workflow that materializes lessons and tasks from events,
  verifies `superseded_by` derivation, confirms legacy tasks do not receive
  incompatible `null` fields, and checks that active and experimental lessons
  enter context while superseded lessons do not.

## Result

G07 implementation is accepted for the covered contract. No core changes were
made during this QA task; only the QA report and end-to-end test were produced.
