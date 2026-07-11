# ONBOARD-001 — Onboarding guiado e perfil governado

## Objetivo

Absorver no ESAA-Core a experiência de onboarding/governança validada no Mira
(sem domínio de slides): perfil de projeto, trilha inicial útil e UX de
tarefas superseded.

## CLI

- `esaa onboard` — interativo por padrão
- `esaa onboard --answers <json>` — reprodutível
- `esaa onboard --dry-run` — simula sem append no event store
- Falha com `ROADMAP_DIR_MISSING` se `.roadmap/` não existir
- Detecta guias existentes (`AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`,
  `README.md`/`readme.md`) sem sobrescrever
- `esaa profile show` — lê projeção `.roadmap/project_profile.json`

## Perfil governado

- Evento reservado: `project.profile.set` (actor orchestrator)
- Projeção: `.roadmap/project_profile.json`
- Schema empacotado: `src/esaa/templates/project_profile.schema.json`
  (copiado no bootstrap; dry-run usa fallback do pacote se o workspace
  ainda não tiver o schema)
- Campos: `project_name`, `domain`, `language`, `sources_of_truth`,
  `output_surfaces`, `protected_paths`, `workflow_preferences`,
  `guide_topology`
- `dispatch-context` inclui resumo compacto quando o perfil existe

## Trilha inicial (criada pelo onboard)

| Task | Kind | Output |
|------|------|--------|
| GOV-PROFILE-001 | spec | docs/spec/GOV-PROFILE-001.md |
| GOV-PROFILE-010 | impl | docs/governance/project-operational-contract.md |
| GOV-PROFILE-020 | qa | docs/qa/project-onboarding.md |

- `supersedes` T-1000/T-1010/T-1020 quando esses seeds estão em `todo`
- IDs já existentes no roadmap não são recriados

## Superseded UX

- Tarefas com `superseded_by` não entram em `eligible` nem em `run`
- Continuam auditáveis em `roadmap.json` / `state`
- `eligible` retorna `suppressed_superseded_count` e `suppressed_superseded`

## Fixture de validação

Workspace real: `/home/elzobrito/desenvolvimento/ESAA-Core-GUI`

- Não mutar worktree nem event store
- `verify ok`, tarefas done, `eligible` vazio
- `onboard --answers <fixture> --dry-run` propõe perfil/trilha sem
  escrever eventos

## Fora de escopo

- Release PyPI nesta rodada
- Comandos/skills/domínio de apresentação do Mira
- Mutações no ESAA-Core-GUI além de dry-run de leitura

## Implementação formal

Cadeia governada: ONBOARD-001 (spec) → ONBOARD-010 (impl) → ONBOARD-020 (qa).
