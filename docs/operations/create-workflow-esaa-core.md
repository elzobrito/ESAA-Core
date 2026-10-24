---
title: "create-workflow × ESAA-Core"
status: saved
date: 2026-07-22
esaa_core: 0.5.0b17
protocol: 0.4.1
author: grok-plan
paths:
  - ~/.grok/docs/plans/create-workflow-esaa-core.md
  - ~/desenvolvimento/ESAA-Core/docs/operations/create-workflow-esaa-core.md
---

# Plano: usar create-workflow para melhorar a utilização do ESAA-Core

> Documento Markdown do plano de harness Grok Build (Rhai) sobre o ESAA-Core.

## Problema que o workflow resolve

Hoje o ESAA-Core é forte em **governança** (event store, gates, two-step, single writer), mas a **utilização** depende de o humano/agente lembrar o ritual:

```text
eligible → dispatch-context → claim → trabalhar → complete(+file_updates) → review → verify
```

Falhas recorrentes (mesmo com o novo `AGENTS.md`):
- colapso de `claim`+`complete` na mesma saída (LES-0001)
- `file_updates` fora de `complete` (LES-0002)
- `prior_status` ausente/errado (LES-0003)
- submit sem `verify` depois
- ignorar lock / runner errado / task de outro actor
- QA e impl misturados no mesmo turno

**create-workflow** (scripts Rhai no Grok Build) não substitui o Orchestrator ESAA. Ele vira o **harness determinístico** que:
1. força fases e ordem (two-step real = dois `agent()` / dois submits);
2. valida envelope JSON com `output_schema` antes de `esaa submit`;
3. chama a CLI `python -m esaa` com `--runner` explícito;
4. pausa em pontos humanos (lock, reject, review);
5. produz relatório auditável do run.

```text
┌─────────────────────────────────────────────────────────┐
│  Grok Workflow (Rhai)  — harness / orquestração local   │
│  phase · agent · parallel · await_user · complete       │
└─────────────┬───────────────────────────────────────────┘
              │  python -m esaa --root <ws> --runner <id>
              ▼
┌─────────────────────────────────────────────────────────┐
│  ESAA-Core Orchestrator  — single writer / gates        │
│  activity.jsonl → projeções roadmap/issues/lessons      │
└─────────────────────────────────────────────────────────┘
```

## Princípios de desenho (não negociáveis)

| Princípio | Por quê |
|-----------|---------|
| Workflow **nunca** edita `activity.jsonl` / read models | Single writer = Orchestrator |
| Toda escrita via CLI `esaa` (`submit`/`claim`/`complete`/`review`) | Proveniência G08 + gates |
| **Um writer por vez** no workspace | Lock operacional atual; `parallel()` só para leitura |
| Two-step = **fases/agents separados**, não um prompt “faça claim e complete” | LES-0001 |
| Envelope validado por schema Rhai **antes** do submit | Reduz `output.rejected` |
| Runner explícito em todo write | `RUNNER_UNKNOWN` em mode strict |
| `await_user` em lock / reject / review humana | Pontos de parada ESAA |
| Efeitos idempotentes ou re-checagem de `state` | Resume de workflow não é exactly-once |

### Gap de runner Grok

Runners registrados no swarm padrão: `claude-cowork`, `claude-code`, `codex`, `human-terminal`, `unattended`.

**Grok não está na lista.** Opções (escolher na implementação):
1. **MVP:** usar `--runner human-terminal` (ou `unattended`) nos submits do workflow.
2. **Correto:** registrar `grok` / `grok-build` em `.roadmap/agents_swarm.yaml` dos workspaces alvo e no template ESAA.

Recomendação: opção 2 no ESAA-Core template + docs; opção 1 só para smoke test.

## Onde salvar os workflows

| Escopo | Path | Quando |
|--------|------|--------|
| User (todos os projetos) | `~/.grok/workflows/esaa-*.rhai` | ritual genérico |
| Repo ESAA-Core | `~/desenvolvimento/ESAA-Core/.grok/workflows/` | exemplos oficiais / docs |
| Repo de produto | `<projeto>/.grok/workflows/` | se o time compartilha harness |

Nomeação: `esaa-health`, `esaa-task-run`, `esaa-qa-review`, `esaa-eligible-loop`.

## Catálogo de workflows (valor incremental)

### 1. `esaa-health` (read-only) — primeiro a construir

**Args:** `root` (path do workspace).

**Fases:**
1. **Probe** — um agent `execute` roda:
   - `test -f "$ROOT/.roadmap/activity.jsonl.lock" && echo LOCKED`
   - `python -m esaa --root "$ROOT" --version`
   - `python -m esaa --root "$ROOT" verify`
   - `python -m esaa --root "$ROOT" eligible`
   - `python -m esaa --root "$ROOT" roadmap status --detail` (se disponível)
2. **Diagnose** — agent `read-only` interpreta outputs e devolve schema `{ ok, lock, verify_ok, eligible_tasks[], blockers[] }`.
3. **Report** — `write_scratch_file` + `complete`.

**Melhora utilização:** onboarding e “o que posso fazer agora?” sem gastar tokens inventando estado.

### 2. `esaa-task-run` (write governado) — core value

**Args:** `root`, `task_id` (opcional; se vazio pega 1ª eligible), `runner`, `actor` (default por `task_kind`), `max_attempts` (default 1).

**Fases sequenciais (nunca claim+complete no mesmo agent):**

```text
phase("Preflight")
  → lock? pause(infra)
  → state / dispatch-context da task
  → se status != todo e não for in_progress do actor → pause/complete com blocker

phase("Claim")
  → agent A: só gera envelope claim (output_schema estrito)
  → agent B (ou mesmo agent com execute): escreve JSON em scratch e
     `python -m esaa --root … --runner … submit --actor … claim.json`
  → se rejected → log + await_user / complete fail-closed

phase("Work+Complete")
  → agent C (capability conforme kind: impl=execute, spec=read-write/execute):
     lê dispatch-context + boundaries; produz complete envelope + file_updates
  → agent D (verificador adversarial, read-only): confere
     - uma activity_event
     - prior_status == in_progress
     - verification.checks com mínimo por kind
     - file_updates só se complete
     - paths dentro de boundaries
  → se verify_agent falhar → fail-closed (não submit)
  → submit complete → verify

phase("Handoff")
  → se task em review e args.auto_review != true → await_user
  → senão opcionalmente acionar esaa-qa-review
```

**Schemas Rhai (esboço):**
- `claim_schema`: `activity_event.action=="claim"`, `task_id`, `prior_status`
- `complete_schema`: `action=="complete"`, `verification.checks` minItems, `file_updates` opcional
- **Proibido no schema de claim:** presença de `file_updates` (ou maxItems 0)

**Melhora utilização:** o AGENTS.md vira **constraint executável** no harness, não só texto.

### 3. `esaa-qa-review` — fan-out de leitura + um review write

**Args:** `root`, `task_id`, `runner`.

**Padrão create-workflow “review → adversarial verify”:**
1. Confirmar `state` = `review`.
2. `parallel()` em dimensões read-only: correctness, contract/boundaries, verification.checks, lessons ativas.
3. Síntese → `decision` approve | request_changes + evidence.
4. **Um** agent write: envelope `review` → submit → verify.
5. Fail-closed se veredictos sem evidence.

**Importante:** parallel só na análise; **um** submit de review.

### 4. `esaa-eligible-loop` — lote sequencial

**Args:** `root`, `limit` (default 3), `kinds` opcional, `runner`.

```text
loop (até limit ou eligible vazio):
  health/lock check
  pick next eligible (Rhai filtra lista; não confiar no agent para inventar task_id)
  invocar lógica de esaa-task-run (inline — workflows não chamam workflows)
  se reject/lock → await_user e sair
```

**Não** usar `parallel()` em tasks que escrevem no mesmo `.roadmap/`.

### 5. `esaa-onboard` — bootstrap de workspace

**Args:** `root`, `profile` (ex. public).

Fases: `bootstrap` → `init` → `verify` → copiar/checar `AGENTS.md` → report “próximo: task create / plugin roadmap”.

Útil para novos projetos e para reduzir fricção do pacote 0.5.x.

## Como o create-workflow se aplica (procedimento)

Seguir a skill `create-workflow` à risca:

1. **Intent** — já definido acima; prioridade sugerida: health → task-run → qa-review.
2. **Author** `.rhai` com `let meta` literal, schemas, fases nomeadas alinhadas a `phase()`.
3. **Smoke-check** `validate_only: true` com args fake (`root` apontando a `esaa-teste` ou workspace throwaway).
4. **Save** em `~/.grok/workflows/esaa-health.rhai` (e seguintes).
5. **Real run** com workspace de teste (`~/desenvolvimento/esaa-teste` se existir).
6. Documentar em skill ESAA ou `docs/operations/` o mapa “workflow ↔ CLI”.

Prompts dos agents devem ser **imperativos e self-contained** (pitfall da skill):
- “Use shell para rodar `python -m esaa …`; não invente status.”
- “Emita **apenas** JSON do envelope; sem markdown.”
- “Não edite `.roadmap/activity.jsonl` nem read models.”
- Incluir trechos curtos do `AGENTS.md` (two-step, LES-0001/2/3) no prompt, não assumir fork_context.

## Mapa AGENTS.md → enforcement no workflow

| Regra AGENTS.md | Onde o workflow impõe |
|-----------------|------------------------|
| Read-only vs governado | `capability_mode` + ausência de submit em health |
| Two-step | fases Claim e Work+Complete separadas |
| Uma action por output | `output_schema` + agent de schema-check |
| file_updates só com complete | schema claim sem file_updates; verifier no complete |
| prior_status coerente | Preflight lê `state`; injeta status real no prompt |
| Lock / um runner | Preflight; pause se lock; sem parallel write |
| done imutável | Preflight: se done → complete report issue path / exit |
| verification.checks mínimos | schema minItems por kind (spec=1, impl=1, qa=1, hotfix=2) |
| Não reabrir done | branch issue.report só com ação explícita do user |

## Integrações laterais (fora do MVP)

| Integração | Papel |
|------------|--------|
| Conversation ESAA | Após complete/review, agent opcional `decide`/`task` no `.conversation-esaa` — **não** misturar stores |
| esaa-codex-plugin | Workflow `esaa-from-requirements` que gera roadmap plugin + activate (write via CLI) |
| alert-tool / notify | Em `await_user` documentar que o operador pode ligar alerta externo |
| Register runner `grok` | Patch em templates `agents_swarm.yaml` + PARCER se necessário |

## Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Workflow resume re-executa submit | Antes de submit, `esaa state`; só claim se `todo` |
| Agent “inteligente” edita store | Prompt + capability; preferir CLI; nunca `search_replace` em `.roadmap/*` no prompt de write |
| Parallel em tasks | Proibido para writes no mesmo root |
| Schema rígido vs evoluções do protocolo | Schemas versionados no header do .rhai; alinhar a `agent_result.schema.json` |
| validate_only não prova CLI real | Smoke em workspace de teste após save |
| Budget de agents | task-run ~4–6 agents/task; eligible-loop `limit` baixo |

## Plano de entrega (implementação, quando sair do plan mode)

1. Registrar (ou documentar) runner `grok` vs uso de `human-terminal`.
2. Implementar `esaa-health.rhai` + smoke-check + save em `~/.grok/workflows/`.
3. Implementar `esaa-task-run.rhai` com schemas claim/complete + adversarial verifier.
4. Rodar em `esaa-teste` (ou workspace sandbox) 1 task `todo` end-to-end.
5. Implementar `esaa-qa-review.rhai`.
6. Atualizar skill `esaa` (seção “Workflows Grok”) e, se desejado, exemplo em `ESAA-Core/docs/operations/` ou `.grok/workflows` no monorepo.
7. Opcional: `esaa-eligible-loop` depois de estabilizar task-run.

## Critérios de sucesso

- Operador roda `/esaa-health root=…` e vê lock + eligible + verify sem prompt ad hoc.
- `/esaa-task-run` nunca submete claim+complete no mesmo JSON (enforçado por fase).
- Taxa de `output.rejected` por envelope inválido cai (schema pré-submit).
- `verify` pós-write faz parte do ritual automático.
- AGENTS.md permanece canônico; workflow é **harness**, não segunda fonte de verdade.

## Fora de escopo deste plano

- Substituir Orchestrator ESAA por lógica Rhai.
- Parallel multi-writer no mesmo `activity.jsonl`.
- Análise das “últimas 10 conversas” (pedido anterior cancelado) — pode ser workflow separado `conversation-esaa` + health.
- Mudanças no protocolo 0.4.1 / esaa-core Python, salvo registro de runner.

## Decisão pendente do usuário (antes de implementar)

1. **Runner stamp:** registrar `grok` no swarm ou usar `human-terminal` no MVP?
2. **Escopo de save:** só `~/.grok/workflows` ou também copiar exemplos para `ESAA-Core`?
3. **MVP:** só `esaa-health` + `esaa-task-run`, ou o pacote completo de 4 workflows?
