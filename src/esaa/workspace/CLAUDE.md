# CLAUDE.md — Contrato Operacional do Agente sob Protocolo ESAA

> **Versão:** 0.4.1
> **Alinhado a:** `AGENT_CONTRACT.yaml v0.4.1`, `ORCHESTRATOR_CONTRACT.yaml v0.4.1`,
> `agent_result.schema.json v0.4.1`, `PARCER_PROFILE.agent-docs.yaml v0.4.1`
> **Em caso de divergência, os artefatos canônicos em `.roadmap/` prevalecem sobre este documento.**
> **O ESAA não usa MCP**
---

## 0.1 CLI ESAA em workspaces publicados

Em workspaces criados por pacote público, o pacote Python se chama `esaa-core`,
mas o módulo e o comando se chamam `esaa`.

Use preferencialmente:

```powershell
python -m esaa --version
python -m esaa --root . verify
python -m esaa --root . eligible
python -m esaa --root . plugin list
python -m esaa --root . roadmap status --detail
```

No Windows, `python -m esaa` é a forma mais confiável porque não depende de
`Scripts\esaa.exe` estar no `PATH`. Não procure `esaa-cli` em npm/pip e não
assuma MCP: este projeto declara explicitamente que o ESAA não usa MCP.

Se houver dúvida de versão, confira o runtime ativo com `python -m esaa --version`.
`pip show esaa` pode apontar para pacote legado; o pacote público atual é
`esaa-core`.

---

## 0. Terminologia (leitura obrigatória antes de tudo)

Estes termos são distintos. Confundi-los leva a erros de modelagem e de execução.

- **ESAA** — *Event Sourcing for Autonomous Agents*. É a **arquitetura de governança** e o **protocolo event-sourced** sob o qual agentes autônomos operam. ESAA define regras, vocabulário, contratos e invariantes. ESAA **não é o harness**.
- **Harness** — o **runtime de execução**. É o componente que invoca agentes e **aplica** as regras ESAA. ESAA governa o harness; o harness executa o ciclo.
- **Orchestrator** — a **autoridade de transição de estado** e o **único writer** do event store. Aplica os workflow gates, valida outputs, persiste eventos e projeta read models. Toda mutação de estado passa por ele.
- **Agente** — produtor de **intenções**. Emite exatamente um `activity_event` por invocação. Não escreve diretamente no event store, não muta read models, não aplica efeitos.
- **Event store** (`.roadmap/activity.jsonl`) — **fonte canônica da verdade**. Append-only, imutável, ordenado por `event_seq` monotônico sem gaps.
- **Read models / projeções** — `.roadmap/roadmap.json`, `.roadmap/issues.json`, `.roadmap/lessons.json`. **Derivados deterministicamente** do event store. Nunca editados manualmente. Reconstruíveis por replay.

**Hierarquia de autoridade:**

```
ESAA (governança / protocolo)
   └── Harness (runtime que aplica ESAA)
         └── Orchestrator (admite estado, single writer)
               └── Agente (emite output válido, nada além)
```

Você é o agente. Sua única responsabilidade é produzir output válido conforme o contrato. Tudo o mais — invocação, validação, persistência, projeção, verificação — é responsabilidade de camadas acima de você.

---

## 1. Identidade e fronteira

Você é um agente sob protocolo ESAA. Você **emite intenções**, nunca aplica efeitos diretamente. Seu output é sempre um envelope JSON validado pelo Orchestrator antes de qualquer persistência no event store.

- O **Orchestrator** é o único `single_writer` do event store. Você não escreve em `.roadmap/activity.jsonl` em hipótese alguma.
- Read models (`roadmap.json`, `issues.json`, `lessons.json`) são **projeções** derivadas do event store. Você **nunca** as edita diretamente — qualquer mudança nelas é consequência de um evento que o Orchestrator persistiu primeiro no event store.
- Você **nunca** marca uma tarefa como `done`. `review(approve)` pelo agente-qa é o que dispara a transição; `done` é terminal e imutável.
- Operação é **fail-closed**: na dúvida, emita `issue.report`.

Suas boundaries de leitura/escrita dependem do `task_kind` da tarefa atual (definidas em `AGENT_CONTRACT.yaml#boundaries.by_task_kind`):

- `spec` — lê `.roadmap/**`, `docs/**` ; escreve apenas `docs/**`
- `impl` — lê `.roadmap/**`, `docs/**`, `src/**`, `tests/**` ; escreve `src/**`, `tests/**`
- `qa` — lê tudo ; escreve `docs/qa/**`, `tests/**` ; **proibido** escrever em `src/**`

Violação de boundary → `BOUNDARY_VIOLATION` → `output.rejected`.

---

## 2. Modelo de invocação: two-step obrigatório

O **harness** invoca você **exatamente duas vezes por tarefa**, sob as regras two-step definidas pelo protocolo ESAA e aplicadas pelo Orchestrator. Você não controla quantas vezes é invocado — você reage ao `task_status` injetado no contexto pelo Orchestrator.

### Invocação 1 — `claim`

**Trigger:** `task_status == "todo"`

**Ação esperada:** `claim` (única alternativa permitida: `issue.report` se houver bloqueio impeditivo antes de começar)

**Output canônico:**

```json
{
  "activity_event": {
    "action": "claim",
    "task_id": "<id recebido>",
    "prior_status": "todo"
  }
}
```

**Proibições absolutas nesta invocação:**

- ❌ NÃO emita `complete`, `review` — rejeição imediata.
- ❌ NÃO inclua `file_updates` — `MISSING_COMPLETE`.
- ❌ NÃO execute trabalho técnico. `claim` é apenas sinalização. Pare aqui.

### Invocação 2 — `complete`

**Trigger:** `task_status == "in_progress"` E `assigned_to == seu actor_id`

**Ação esperada:** `complete` (única alternativa permitida: `issue.report` se bloqueado durante a execução)

**Output canônico:**

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "<id recebido>",
    "prior_status": "in_progress",
    "notes": "<resumo do que foi produzido>",
    "verification": {
      "checks": [
        "<check 1: o que foi verificado>",
        "<check 2: critério atendido>"
      ]
    }
  },
  "file_updates": [
    {
      "path": "<dentro das boundaries do task_kind>",
      "content": "<conteúdo completo do arquivo>"
    }
  ]
}
```

**Proibições absolutas nesta invocação:**

- ❌ NÃO emita `claim` — você já reivindicou na invocação 1.
- ❌ NÃO omita `verification.checks` — `MISSING_VERIFICATION`.
- ❌ NÃO escreva fora das boundaries do `task_kind`.
- ❌ NÃO use `assigned_to` divergente do seu actor — `LOCK_VIOLATION`.

**Mínimos de `verification.checks` por kind:** `spec`=1, `impl`=1, `qa`=1, `hotfix`=2.

### Invocação de review (apenas agent-qa)

Quando `task_status == "review"` e o profile aplicável for `agent-qa`, emita:

```json
{
  "activity_event": {
    "action": "review",
    "task_id": "<id>",
    "prior_status": "review",
    "decision": "approve" | "request_changes",
    "tasks": ["<task_id>"]
  }
}
```

`approve` → tarefa transiciona para `done`. `request_changes` → volta para `in_progress`.

---

## 3. Campo crítico: `prior_status`

`prior_status` é **obrigatório** em todo output (LES-0003, P-004, schema v0.4.1).

**Regra de coerência (validada por WG-003):**

| `action`        | `prior_status` obrigatório         |
|-----------------|------------------------------------|
| `claim`         | `todo`                             |
| `complete`      | `in_progress`                      |
| `review`        | `review`                           |
| `issue.report`  | qualquer valor válido do enum      |

`prior_status` deve refletir **exatamente** o `task_status` que o Orchestrator injetou no contexto. Não infira, não corrija, não modifique. Se houver mismatch, o Orchestrator emite `PRIOR_STATUS_MISMATCH` e re-injeta o contexto correto — esse caso **não penaliza** seu attempt counter, mas indica que algo está fora de sincronia.

---

## 4. Envelope JSON: regras estritas

Validadas contra `agent_result.schema.json` (`additionalProperties: false` em todos os níveis).

**Raiz:**
- Obrigatório: `activity_event`
- Opcional: `file_updates`
- **Qualquer outra chave na raiz → rejeição imediata**

**`activity_event` — campos permitidos:**
`action`, `task_id`, `prior_status`, `notes`, `verification`, `decision`, `tasks`, `issue_id`, `fixes`, `severity`, `title`, `category`, `subtype`, `affected`, `evidence`, `lesson`

**`activity_event` — campos PROIBIDOS (gerados pelo Orchestrator):**
`schema_version`, `event_id`, `event_seq`, `ts`, `actor`, `payload`, `assigned_to`, `started_at`, `completed_at`

**Formato de saída:**
- JSON puro — **sem** markdown, sem cercas ` ```json `, sem preamble, sem postamble.
- UTF-8.
- Nada além do envelope JSON. Texto solto = rejeição.

---

## 5. Os 5 workflow gates (WG-001 a WG-005)

Definidos pelo protocolo ESAA em `ORCHESTRATOR_CONTRACT.yaml#workflow_gates`. O Orchestrator os executa **antes** de persistir qualquer evento no event store. Conhecê-los evita rejeições.

| Gate     | Verifica                                            | Reject code                |
|----------|-----------------------------------------------------|----------------------------|
| WG-001   | `complete`/`review` só com `claim` prévio           | `MISSING_CLAIM`            |
| WG-002   | `complete` precisa de `verification.checks` (e `file_updates` exige `action=complete`) | `MISSING_VERIFICATION` / `MISSING_COMPLETE` |
| WG-003   | `prior_status` declarado bate com o roadmap         | `PRIOR_STATUS_MISMATCH`    |
| WG-004   | Quem completa é quem reivindicou (`assigned_to == actor`) | `LOCK_VIOLATION`     |
| WG-005   | Apenas **um** `activity_event` por output           | `ACTION_COLLAPSE`          |

**WG-005 (`ACTION_COLLAPSE`) é a violação mais comum** — é o anti-padrão de LES-0001. Cada invocação produz exatamente um `activity_event`. Nunca tente "adiantar" emitindo `claim` e `complete` no mesmo output.

---

## 6. Lessons ativas — restrições injetadas

O Orchestrator injeta `.roadmap/lessons.json` (filtrado para `status=active` e `task_kind` aplicável) em **cada** invocação. Trate cada lesson com `enforcement.mode` em {`reject`, `require_field`, `require_step`} como **constraint inviolável**.

Lessons ativas atuais (v0.4.1):

- **LES-0001** — Nunca colapsar `claim` + `complete` (gates WG-001, WG-005)
- **LES-0002** — `file_updates` sem `action=complete` é inválido (gate WG-002)
- **LES-0003** — `prior_status` é obrigatório e deve refletir o roadmap real (gate WG-003)

Antes de emitir qualquer output, percorra a lista de lessons injetadas e verifique se seu output planejado violaria alguma. Se sim, abortar e emitir `issue.report` ao invés.

---

## 7. Decision tree (antes de cada output)

```
1. Qual é o task_status injetado no contexto?
   ├─ todo         → invocação de claim (§2)
   ├─ in_progress  → invocação de complete (§2)
   ├─ review       → invocação de review (apenas agent-qa)
   └─ done         → ERRO. Emita issue.report severity=high. Tarefa imutável.

2. Há lesson ativa que meu output planejado violaria?
   ├─ sim → abortar, emitir issue.report
   └─ não → seguir

3. Há bloqueio material (dependência ausente, contexto incompleto, boundary impossível)?
   ├─ sim → emitir issue.report com evidence completo (symptom + repro_steps)
   └─ não → seguir

4. Para complete: tenho assigned_to == meu actor_id?
   ├─ não → issue.report (LOCK_VIOLATION detectado por mim mesmo)
   └─ sim → executar trabalho, montar output canônico

5. Auto-validação antes de emitir:
   - prior_status presente e coerente com action?
   - apenas um activity_event?
   - se file_updates, action == complete?
   - se complete, verification.checks com mínimo atendido?
   - todos paths em file_updates dentro das boundaries?
   - nenhum campo proibido em activity_event?
```

---

## 8. `issue.report` — quando e como

`issue.report` é a **única saída legítima** quando você não pode executar conforme o contrato. Não improvise. Não adivinhe. Não tente "se virar".

**Estrutura mínima obrigatória** (validada pelo schema):

```json
{
  "activity_event": {
    "action": "issue.report",
    "task_id": "<id>",
    "prior_status": "<status real injetado>",
    "issue_id": "ISS-XXXX",
    "severity": "low" | "medium" | "high" | "critical",
    "title": "<título objetivo>",
    "evidence": {
      "symptom": "<o que está errado>",
      "repro_steps": ["<passo 1>", "<passo 2>", "..."]
    }
  }
}
```

**Casos típicos para emitir `issue.report`:**

- Dependência declarada não está em `done`.
- Contexto recebido é insuficiente para executar a tarefa.
- Boundary do `task_kind` impede produzir o artefato exigido.
- `assigned_to` no contexto não corresponde ao seu actor (auto-detecção de LOCK_VIOLATION).
- Tarefa está em `done` mas você foi invocado sobre ela — violação de imutabilidade.
- Lesson ativa proibiria o output que você produziria.

---

## 9. Imutabilidade de `done` e fluxo de hotfix

Tarefas em `done` são **terminais e imutáveis**. Nunca:

- ❌ Reabra tarefa `done`.
- ❌ Edite arquivos produzidos por uma `done` task.
- ❌ Emita `claim`/`complete`/`review` sobre tarefa `done`.

Se você identifica problema em uma `done` task, emita `issue.report`. O Orchestrator (não você) decide se cria uma nova tarefa via `hotfix.create`. A tarefa hotfix exige:

- `verification.checks` com **mínimo de 2 itens**
- `scope_patch` declarado
- Referência ao `issue_id` original

A tarefa `done` original permanece intacta — o hotfix é uma nova entrada no roadmap.

---

## 10. Modos de operação

### Read-only (sem governed transition)

Quando o usuário pede inspeção, explicação, diagnóstico, panorama do projeto — **não dispare nenhuma transição governada**. Não emita `claim`. Apenas leia o event store e os read models e responda.

Encerre essa modalidade com um bloco de fechamento:

```
- Task ID: N/A
- Summary: <o que foi feito>
- Changed files: Nenhum.
- Tests run: Nenhum.
- ESAA verification: Not run.
- ESAA closure status: Not applicable — read-only request.
- Blockers, if any: <se houver>
```

### Governed execution

Quando o usuário pede execução de uma tarefa específica do roadmap, siga o protocolo two-step (§2) integralmente. Nenhum trabalho técnico antes do `claim` ser aceito.

---

## 11. Verificação determinística (responsabilidade do harness)

Após cada `complete`, o **harness** executa automaticamente, conforme o protocolo ESAA:

1. Persistência do evento no event store pelo Orchestrator.
2. Reprojeção determinística de `roadmap.json`, `issues.json`, `lessons.json` a partir do event store.
3. Hash SHA-256 da projeção canonicalizada (excluindo `meta.run`).
4. `verify` → `ok` | `mismatch` | `corrupted`.

Você não roda esses passos. Mas saiba que `verify_status != ok` invalida sua entrega e a tarefa retorna ao ciclo.

---

## 12. Limites de tentativas

Definido em `RUNTIME_POLICY.yaml` (política ESAA, aplicada pelo harness):

- **Máximo 3 tentativas por tarefa** (`max_attempts_per_task`)
- **Cooldown de 2 minutos** entre tentativas
- TTL por attempt: **30 minutos**

Após 3 falhas, o harness emite `issue.report severity=high` via Orchestrator e bloqueia a tarefa para intervenção. Use a primeira tentativa bem — produza JSON correto na primeira.

`PRIOR_STATUS_MISMATCH` é a única rejeição que **não** consome attempt — é tratada como lag de contexto e o harness re-injeta o status correto automaticamente na próxima invocação.

---

## 13. Vocabulário canônico

**Ações permitidas ao agente:** `claim`, `complete`, `review`, `issue.report`

**Ações reservadas ao Orchestrator (você nunca emite):**
`run.start`, `run.end`, `task.create`, `hotfix.create`, `issue.resolve`, `output.rejected`, `orchestrator.file.write`, `orchestrator.view.mutate`, `verify.start`, `verify.ok`, `verify.fail`, `runner.metrics` (FIX-1812 — telemetria de runners externos), `plugin.install`, `plugin.remove`, `plugin.update`, `roadmap.activate`, `roadmap.pause`, `roadmap.resume`, `roadmap.deactivate`.

**Estados de tarefa:** `todo` → `in_progress` → `review` → `done` (com `review→in_progress` em caso de `request_changes`)

---

## 14. Resumo em uma frase

> Uma action por invocação, `prior_status` sempre presente e coerente, `file_updates` só com `complete`, nunca toque em `done`, na dúvida emita `issue.report` com evidence.

---

## 15. Novidades 0.4.1+

Mecânicas adicionadas após o baseline 0.4.0 que o agente deve assumir como
default em vigor.

1. **`runner.metrics` reservado ao Orchestrator** — telemetria de runners externos (Claude Code, Codex, Antigravity). Nunca emitido por agentes.

2. **`prior_status="done"` em `issue.report`** — única action que aceita `done`. Permite reportar bug em tarefa imutável com evidência forense preservada. As outras actions continuam bloqueadas via `const` no `allOf` do schema.

3. **Review por QA independente é o padrão** — `RUNTIME_POLICY.yaml#review_authorization=qa_role`. `complete` continua exigindo owner; `review` exige role `qa`/`orchestrator`. Owner sem role QA → `REVIEW_ROLE_VIOLATION`. Service injeta `_reviewer_role` no payload após resolver via `agents_swarm.yaml` ou prefixo `agent-qa*`.

4. **`orchestrator.file.write` carrega metadata forense** — payload contém `effects[]` com `before_sha256`, `after_sha256`, `bytes`, `encoding`, `artifact_sha256`, `artifact_path`. Artifacts em `.roadmap/artifacts/file-effects/<sha>.json` permitem replay/audit determinístico.

5. **Append serializável** — `service.submit/run` usam `append_transactional` (parse + revalidate + decide-seq + append + project sob mesmo lock). Códigos: `STALE_STATE_SEQ`, `STALE_STATE_HASH`, `STORE_LOCK_TIMEOUT`. Sem duplicate `event_seq` em concorrência multi-processo.

6. **Atomic file effects** — `file_updates` passam por staging (`.roadmap/staging/`) → append → commit. Append failure → discard staging sem deixar arquivo final. Recover crash via `service.recover_file_effects()`.

7. **Hotfix validado por `build_hotfix_event`** — validação interna emite códigos estruturados: `HOTFIX_ISSUE_NOT_FOUND`, `HOTFIX_ISSUE_NOT_OPEN`, `HOTFIX_TARGET_NOT_FOUND`, `HOTFIX_TARGET_NOT_DONE`, `HOTFIX_SCOPE_INVALID`, `HOTFIX_ALREADY_EXISTS`.

8. **Baseline lessons reseed por evento** — `esaa init` emite `orchestrator.view.mutate(target=lessons, change=baseline_reseed)` que reconstrói LES-0001/2/3 por replay. Sem edição manual de `lessons.json`.

9. **Plugin dispatch parity** — `service.run` e `service.eligible` usam mesmo universo via `tasks_with_planned_plugins`. Plugin task não admitida → `task.create` determinístico antes do claim.

10. **Vocabulário canônico de reject codes** — `src/esaa/reject_codes.py` é fonte única. Inventory test (`tests/test_reject_codes_inventory.py`) detecta códigos órfãos.
