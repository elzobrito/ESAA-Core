# ONBOARD-020 — Evidência de QA do onboarding guiado

## Escopo

Validar a implementação formalizada em ONBOARD-001/010:
onboard, project profile, trilha GOV-PROFILE e superseded UX.

## Testes automatizados

Comando:

```bash
cd /home/elzobrito/desenvolvimento/ESAA-Core
PYTHONPATH=src python -m pytest tests/test_project_profile_onboarding.py -q
```

Resultado: **5 passed** (2026-07-10).

Cobertura:
- `ROADMAP_DIR_MISSING` sem `.roadmap/`
- dry-run não muta eventos nem guias
- onboard cria perfil + `GOV-PROFILE-*` e `profile show` lê projeção
- `dispatch-context` inclui resumo do perfil
- seeds superseded ocultos em `eligible`, auditáveis em `state`
- fixture real `ESAA-Core-GUI` dry-run (se presente)

## Fixture real ESAA-Core-GUI

```bash
PYTHONPATH=src python -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core-GUI verify
PYTHONPATH=src python -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core-GUI eligible
PYTHONPATH=src python -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core-GUI onboard --answers <fixture> --dry-run
```

Resultados:
- `verify_status: ok`, `last_event_seq: 533`, `project_profile: false`
- `eligible_count: 0`
- dry-run: `status: dry_run`, propõe `project.profile.set` + `GOV-PROFILE-001/010/020` (6 eventos simulados)
- `activity.jsonl` **533 → 533** (sem mutação)
- guias detectados: `AGENTS.md`, `.claude/CLAUDE.md`, `readme.md` (sem overwrite)

## Verify do ESAA-Core (workspace de implementação)

Após cadeia ONBOARD-001/010:

```bash
PYTHONPATH=src python -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core verify
```

Executado no fluxo QA; ver resultado final pós-complete desta tarefa.

## Critérios

| Critério | Status |
|----------|--------|
| pytest onboarding passa | OK |
| Dry-run GUI não altera store | OK |
| Feature presente no código governado | OK |

## Fora de escopo / riscos conhecidos

- Worktree do ESAA-Core ainda pode ter alterações **não** do plano
  (ex.: `boundary_paths`, security boundary tests) fora desta cadeia.
- Schema G07 (`task_type`/`acceptance_criteria`) no `.roadmap/roadmap.schema.json`
  local do Core ainda não aceita esses campos no `task create` sem rebootstrap
  do schema; tarefas ONBOARD-* foram criadas sem esses campos opcionais.
- Release PyPI não faz parte deste plano.
