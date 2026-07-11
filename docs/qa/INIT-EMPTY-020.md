# INIT-EMPTY-020 — QA init vazio e flag demo

## Escopo

Validar INIT-EMPTY-001/010: `esaa init` sem tasks demo por default; `--with-demo-tasks` semeia T-1000/1010/1020.

## Pytest

```text
........                                                                 [100%]
8 passed in 0.99s
```

## Cenario manual (tmp workspace)

### init default
```json
{
  "run_id": "RUN-0001",
  "events_written": 4,
  "last_event_seq": 4,
  "projection_hash_sha256": "411885afdc5e0e74e1eac70f8cef0094ef6842c1b5c11b34654bb1e3b0664d50",
  "with_demo_tasks": false,
  "tasks_seeded": [],
  "task_source": "empty"
}
```
- task_source: **empty**
- tasks_seeded: **[]**
- eligible_count: **0**

### init --force --with-demo-tasks
```json
{
  "task_source": "demo",
  "tasks_seeded": [
    "T-1000",
    "T-1010",
    "T-1020"
  ],
  "last_event_seq": 7,
  "with_demo_tasks": true
}
```
- eligible_count apos demo: **1**

## ESAA-Core verify

```json
{
  "verify_status": "ok",
  "last_event_seq": 641,
  "projection_hash_sha256": "b9ace60c20e6200fc27793b46205539b4b5d119ca5733b0577e07b21599dfdec",
  "project_profile": false
}
```

## Criterios

| Criterio | Status |
|----------|--------|
| init vazio default | PASS (empty) |
| flag demo seeds T-1000 | PASS (['T-1000', 'T-1010', 'T-1020']) |
| pytest init empty | PASS (ver log acima) |
| verify Core ok | PASS (ok) |

## Conclusao

**PASS** — formalizacao INIT-EMPTY pronta para uso.
