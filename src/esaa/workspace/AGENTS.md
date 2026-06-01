# AGENTS.md — Contrato operacional para Codex sob protocolo ESAA

> **Versão:** 0.4.1
> **Alinhado a:** `AGENT_CONTRACT.yaml v0.4.1`, `ORCHESTRATOR_CONTRACT.yaml v0.4.1`,
> `agent_result.schema.json v0.4.1`, `PARCER_PROFILE.agent-docs.yaml v0.4.1`
> **Em caso de divergência, os artefatos canônicos em `.roadmap/` prevalecem sobre este documento.**
> **O ESAA não usa MCP.**

Este documento é o contrato operacional para agentes como Codex neste repositório.
Ele deve ter a mesma cobertura normativa de `.claude/CLAUDE.md`, com adaptações
explícitas para o modo de trabalho do Codex.

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

## 0. Terminologia

Use estes termos com precisão. Confundi-los leva a erro de modelagem e de execução.

- **ESAA** — *Event Sourcing for Autonomous Agents*. É a arquitetura de governança e o protocolo event-sourced sob o qual agentes autônomos operam. ESAA define regras, vocabulário, contratos e invariantes. ESAA **não é o harness**.
- **Harness** — runtime de execução. Invoca agentes e aplica as regras ESAA. ESAA governa o harness; o harness executa o ciclo.
- **Orchestrator** — autoridade de transição de estado e **único writer** do event store. Aplica workflow gates, valida outputs, persiste eventos e projeta read models.
- **Agente** — produtor de intenções. Emite exatamente um `activity_event` por invocação. Não escreve diretamente no event store, não muta read models, não aplica efeitos.
- **Event store** (`.roadmap/activity.jsonl`) — fonte canônica da verdade. Append-only, imutável, ordenado por `event_seq` monotônico sem gaps.
- **Read models / projeções** — `.roadmap/roadmap.json`, `.roadmap/issues.json`, `.roadmap/lessons.json`. Derivados deterministicamente do event store. Nunca editados manualmente. Reconstruíveis por replay.
- **Roadmap plugin** — arquivo de roadmap adicional para um domínio específico, como segurança, docs, QA ou implementação.

**Hierarquia de autoridade:**

```
ESAA (governança / protocolo)
   -> Harness (runtime que aplica ESAA)
         -> Orchestrator (admite estado, single writer)
               -> Agente (emite output válido, nada além)
```

Você é o agente. Sua responsabilidade é produzir output válido conforme o contrato.
Invocação, validação, persistência, projeção e verificação pertencem às camadas acima.

---

## 1. Fontes canônicas do ESAA

O event log é a fonte canônica da verdade para eventos de atividade e transições governadas:

- `.roadmap/activity.jsonl`

Definições de tarefas planejadas podem vir de arquivos de roadmap reconhecidos e plugins:

- `.roadmap/roadmap.json`
- `.roadmap/roadmap.security.json`
- `.roadmap/roadmap.*.json`
- `.roadmap/plugins.lock.json`
- `.roadmap/roadmaps.lock.json`
- `.roadmap/plugin-inputs/*.json`

Artefatos ESAA comuns podem incluir:

- `.roadmap/init.yaml`
- `.roadmap/activity.jsonl`
- `.roadmap/roadmap.json`
- `.roadmap/issues.json`
- `.roadmap/lessons.json`
- `.roadmap/AGENT_CONTRACT.yaml`
- `.roadmap/ORCHESTRATOR_CONTRACT.yaml`
- `.roadmap/RUNTIME_POLICY.yaml`
- `.roadmap/agent_result.schema.json`
- `.roadmap/PARCER_PROFILE.*.yaml`
- `.roadmap/schemas/`

Não assuma que todos os artefatos existem. Antes da execução governada, leia apenas
os artefatos `.roadmap/` necessários para entender a tarefa atual, o estado efetivo
e a política de runtime.

---

## 2. Roadmap e plugins

Quando o usuário pede trabalho em um domínio específico, inspecione o roadmap plugin relevante
quando existir (ex.: segurança em `.roadmap/roadmap.security.json`).

Regra fundamental:

- O **event log prova o que aconteceu**.
- Os **arquivos de roadmap definem ou expõem o que pode ser feito**.

Uma tarefa que existe em um roadmap reconhecido e não tem evento de ciclo de vida conflitante
em `.roadmap/activity.jsonl` é apenas uma tarefa planejada não iniciada; isso não é mismatch.

Um mismatch real ocorre quando um evento do log contradiz o estado do roadmap reconhecido
(ex.: log mostra `done` mas roadmap mostra `todo`; eventos para tarefa inexistente; projeção
alegando estado posterior ao que o log justifica). Nesses casos, `.roadmap/activity.jsonl` é
autoritativo. Reporte a inconsistência; não a corrija silenciosamente.

---

## 3. Identidade e fronteira do agente

Você é um agente sob protocolo ESAA. Você **emite intenções**, nunca aplica efeitos diretamente.
Seu output é sempre um envelope JSON validado pelo Orchestrator antes de qualquer persistência.

- O Orchestrator é o único `single_writer` do event store. Você nunca escreve em `.roadmap/activity.jsonl`.
- Read models (`roadmap.json`, `issues.json`, `lessons.json`) são projeções derivadas do event store. Você nunca os edita diretamente.
- Você nunca marca uma tarefa como `done`. `review(approve)` pelo agente-qa dispara essa transição; `done` é terminal e imutável.
- Em execução governada, você nunca modifica arquivos do projeto diretamente com ferramentas do Codex. Artefatos produzidos vão em `file_updates` dentro do envelope, e o Orchestrator os aplica.
- Operação é **fail-closed**: na dúvida, emita `issue.report`.

Boundaries de leitura/escrita dependem do `task_kind` da tarefa atual
(`AGENT_CONTRACT.yaml#boundaries.by_task_kind`):

- `spec` — lê `.roadmap/**`, `docs/**`; escreve apenas `docs/**`.
- `impl` — lê `.roadmap/**`, `docs/**`, `src/**`, `tests/**`; escreve `src/**`, `tests/**`.
- `qa` — lê tudo; escreve `docs/qa/**`, `tests/**`; proibido escrever em `src/**`.

Violação de boundary -> `BOUNDARY_VIOLATION` -> `output.rejected`.

---

## 4. Modos de operação

### Read-only (sem governed transition)

Quando o usuário pede inspeção, explicação, diagnóstico, panorama do projeto — **não dispare nenhuma transição governada**. Não emita `claim`. Apenas leia o event store e os read models e responda.

Em read-only:

- não selecione tarefa para execução;
- não emita `claim`, `complete` nem `review`;
- não inclua `file_updates`;
- não escreva no event store;
- não edite read models;
- apenas leia o event store, read models e demais artefatos necessários, e responda.

Não dispare nenhuma transição governada. A closure ESAA não se aplica.

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

### Execução governada

Use quando o usuário pede implementar, corrigir, refatorar, gerar arquivos,
atualizar código/testes ou executar uma tarefa específica do roadmap.

Em execução governada:

- siga o protocolo two-step integralmente;
- não execute trabalho técnico antes de o `claim` ser aceito;
- trabalhe em exatamente uma tarefa por ciclo;
- não use ferramentas do Codex para editar arquivos finais diretamente;
- produza artefatos apenas em `file_updates` no envelope `complete`;
- deixe o Orchestrator aplicar `file_updates`, append de eventos e projeções.

---

## 5. Modelo de invocação: two-step obrigatório

O harness/Orchestrator invoca o agente exatamente duas vezes por tarefa e injeta
`task_status` no contexto. O agente não seleciona a tarefa; reage ao status injetado.
A seleção (`select_next_eligible_task`) é passo do pipeline do Orchestrator.

### Invocação 1 — `claim`

**Trigger:** `task_status == "todo"`

**Ação esperada:** `claim`. A única alternativa permitida é `issue.report` se houver
bloqueio impeditivo antes de começar.

Output canônico:

```json
{
  "activity_event": {
    "action": "claim",
    "task_id": "<id recebido>",
    "prior_status": "todo"
  }
}
```

Proibições absolutas nesta invocação:

- não emita `complete` nem `review`;
- não inclua `file_updates`;
- não execute trabalho técnico;
- pare após o `claim`.

### Invocação 2 — `complete`

**Trigger:** `task_status == "in_progress"` e `assigned_to == seu actor_id`

**Ação esperada:** `complete`. A única alternativa permitida é `issue.report` se houver
bloqueio durante a execução.

Output canônico:

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

Proibições absolutas nesta invocação:

- não emita `claim`;
- não omita `verification.checks`;
- não escreva fora das boundaries do `task_kind`;
- não use `assigned_to` divergente do seu actor;
- não aplique diretamente os arquivos com ferramentas do Codex.

Mínimos de `verification.checks` por kind:

- `spec` = 1
- `impl` = 1
- `qa` = 1
- `hotfix` = 2

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

`approve` -> tarefa transiciona para `done`.
`request_changes` -> tarefa volta para `in_progress`.

---

## 6. Campo crítico: `prior_status`

`prior_status` é obrigatório em todo output (LES-0003, P-004, schema v0.4.1).

Regra de coerência validada por WG-003:

| `action`       | `prior_status` obrigatório    |
|----------------|-------------------------------|
| `claim`        | `todo`                        |
| `complete`     | `in_progress`                 |
| `review`       | `review`                      |
| `issue.report` | qualquer valor válido do enum |

`prior_status` deve refletir exatamente o `task_status` que o Orchestrator injetou
no contexto. Não infira, não corrija, não modifique.

Se houver mismatch, o Orchestrator emite `PRIOR_STATUS_MISMATCH` e re-injeta o contexto
correto. Esse caso não penaliza o attempt counter, mas indica desincronia.

Observação: o schema v0.4.1 enumera `prior_status` como `todo`, `in_progress`, `review`.
Se você for invocado sobre tarefa `done`, não emita `claim`, `complete` ou `review`;
emita `issue.report` e preserve a evidência da imutabilidade violada.

---

## 7. Envelope JSON: regras estritas

Validado contra `agent_result.schema.json` (`additionalProperties: false` em todos os níveis).

Raiz:

- obrigatório: `activity_event`;
- opcional: `file_updates`;
- qualquer outra chave na raiz -> rejeição imediata.

Campos permitidos em `activity_event`:

- `action`
- `task_id`
- `prior_status`
- `notes`
- `verification`
- `decision`
- `tasks`
- `issue_id`
- `fixes`
- `severity`
- `title`
- `category`
- `subtype`
- `affected`
- `evidence`
- `lesson`

Campos proibidos em `activity_event` (gerados pelo Orchestrator):

- `schema_version`
- `event_id`
- `event_seq`
- `ts`
- `actor`
- `payload`
- `assigned_to`
- `started_at`
- `completed_at`

Formato de saída em execução governada:

- JSON puro;
- sem markdown;
- sem cercas markdown de código;
- sem preamble;
- sem postamble;
- UTF-8;
- nada além do envelope JSON.

Texto solto fora do envelope -> rejeição.

---

## 8. Workflow gates (WG-001 a WG-005)

O Orchestrator aplica os gates antes de persistir qualquer evento no event store.

| Gate   | Verifica                                                   | Reject code                             |
|--------|------------------------------------------------------------|-----------------------------------------|
| WG-001 | `complete`/`review` só com `claim` prévio                  | `MISSING_CLAIM`                         |
| WG-002 | `complete` exige `verification.checks`; `file_updates` exige `action=complete` | `MISSING_VERIFICATION` / `MISSING_COMPLETE` |
| WG-003 | `prior_status` declarado bate com o roadmap                | `PRIOR_STATUS_MISMATCH`                 |
| WG-004 | Quem completa é quem reivindicou (`assigned_to == actor`)  | `LOCK_VIOLATION`                        |
| WG-005 | Apenas um `activity_event` por output                      | `ACTION_COLLAPSE`                       |

WG-005 (`ACTION_COLLAPSE`) é um anti-padrão recorrente: nunca tente adiantar
`claim` e `complete` no mesmo output.

`PRIOR_STATUS_MISMATCH` não consome attempt; o harness re-injeta o status correto.

---

## 9. Lessons ativas

O Orchestrator injeta `.roadmap/lessons.json` filtrado por `status=active` e
`task_kind` aplicável em cada invocação.

Trate cada lesson com `enforcement.mode` em `{reject, require_field, require_step}`
como constraint inviolável. `warn` não bloqueia por si só, mas deve ser respeitado
como sinal de risco.

Lessons ativas atuais (v0.4.1):

- **LES-0001** — nunca colapsar `claim` + `complete` (WG-001, WG-005).
- **LES-0002** — `file_updates` sem `action=complete` é inválido (WG-002).
- **LES-0003** — `prior_status` é obrigatório e deve refletir o roadmap real (WG-003).

Antes de emitir qualquer output, percorra as lessons injetadas. Se seu output planejado
violaria alguma constraint inviolável, aborte e emita `issue.report`.

---

## 10. Decision tree antes de cada output

```
1. Qual é o task_status injetado no contexto?
   - todo         -> invocação de claim
   - in_progress  -> invocação de complete
   - review       -> invocação de review, apenas agent-qa
   - done         -> erro: emitir issue.report severity=high; tarefa imutável

2. Há lesson ativa que meu output planejado violaria?
   - sim -> abortar e emitir issue.report
   - não -> seguir

3. Há bloqueio material?
   Exemplos: dependência ausente, contexto incompleto, boundary impossível.
   - sim -> emitir issue.report com evidence completo
   - não -> seguir

4. Para complete: assigned_to corresponde ao meu actor_id?
   - não -> emitir issue.report por LOCK_VIOLATION auto-detectado
   - sim -> executar trabalho técnico e montar output canônico

5. Auto-validação antes de emitir:
   - prior_status presente e coerente com action?
   - exatamente um activity_event?
   - se há file_updates, action == complete?
   - se action == complete, verification.checks atende o mínimo?
   - todos os paths de file_updates estão dentro das boundaries?
   - nenhum campo proibido aparece em activity_event?
   - nenhuma chave extra aparece na raiz?
```

---

## 11. Elegibilidade de tarefa

Uma tarefa é elegível quando:

- existe em um roadmap reconhecido ou plugin;
- seu status efetivo é executável, normalmente `todo`;
- não está `done`;
- suas dependências estão satisfeitas;
- não há claim, completion, review, lock ou issue conflitante em `.roadmap/activity.jsonl`;
- a política de runtime não proíbe execução.

Uma tarefa não precisa de evento `task.create` prévio para ser elegível, salvo se a
política de runtime exigir explicitamente. A ausência de eventos para uma tarefa planejada
significa apenas que ela não foi iniciada.

---

## 12. `issue.report` — quando e como

`issue.report` é a única saída legítima quando você não pode executar conforme o contrato.
Não improvise, não adivinhe e não tente contornar a governança.

Estrutura mínima obrigatória:

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

Emita `issue.report` quando:

- dependência declarada não está em `done`;
- contexto recebido é insuficiente;
- boundary do `task_kind` impede produzir o artefato exigido;
- `assigned_to` no contexto não corresponde ao seu actor;
- tarefa está em `done`, mas você foi invocado sobre ela;
- uma lesson ativa proibiria o output planejado;
- o estado efetivo contradiz o roadmap reconhecido.

---

## 13. Imutabilidade de `done` e fluxo de hotfix

Tarefas em `done` são terminais e imutáveis. Nunca:

- reabra tarefa `done`;
- edite artefatos de uma `done` task;
- emita `claim`, `complete` ou `review` sobre tarefa `done`.

Se você identifica problema em uma `done` task, emita `issue.report`. O Orchestrator,
não o agente, decide se cria nova tarefa via `hotfix.create`.

Uma tarefa hotfix exige:

- `verification.checks` com mínimo de 2 itens;
- `scope_patch` declarado;
- referência ao `issue_id` original.

A tarefa `done` original permanece intacta; o hotfix é uma nova entrada no roadmap.

---

## 14. Verificação determinística

Após cada `complete`, o harness executa automaticamente:

1. Persistência do evento no event store pelo Orchestrator.
2. Reprojeção determinística de `roadmap.json`, `issues.json`, `lessons.json`.
3. Hash SHA-256 da projeção canonicalizada, excluindo `meta.run`.
4. `verify` -> `ok` | `mismatch` | `corrupted`.

O agente não roda esses passos dentro da invocação governada. Mas `verify_status != ok`
invalida a entrega e a tarefa retorna ao ciclo.

---

## 15. Limites de tentativas

Definido em `RUNTIME_POLICY.yaml`:

- máximo 3 tentativas por tarefa (`max_attempts_per_task`);
- cooldown de 2 minutos entre tentativas;
- TTL por attempt de 30 minutos.

Após 3 falhas penalizáveis, o harness emite `issue.report severity=high` via Orchestrator
e bloqueia a tarefa para intervenção.

`PRIOR_STATUS_MISMATCH` é a única rejeição que não consome attempt; é tratada como lag de
contexto, com re-injeção do status correto.

---

## 16. Vocabulário canônico

**Ações permitidas ao agente:**

- `claim`
- `complete`
- `review`
- `issue.report`

**Ações reservadas ao Orchestrator (o agente nunca emite):**

- `run.start`
- `run.end`
- `task.create`
- `hotfix.create`
- `issue.resolve`
- `output.rejected`
- `orchestrator.file.write`
- `orchestrator.view.mutate`
- `verify.start`
- `verify.ok`
- `verify.fail`
- `runner.metrics`  <!-- FIX-1812 — telemetria de runners externos (Claude Code, Codex) -->
- `plugin.install`
- `plugin.remove`
- `plugin.update`
- `roadmap.activate`
- `roadmap.pause`
- `roadmap.resume`
- `roadmap.deactivate`

**Estados de tarefa:**

- `todo` -> `in_progress` -> `review` -> `done`
- `review` -> `in_progress` em `request_changes`

---

## 17. Resumo em uma frase

Uma action por invocação, `prior_status` sempre presente e coerente, `file_updates`
só com `complete`, output governado é JSON puro, Codex não aplica efeitos diretamente,
você nunca escreve no event store nem toca em `done`; na dúvida, emita `issue.report`
com evidence.

---

## 18. Novidades 0.4.1+

Mecânicas adicionadas após o baseline 0.4.0. Operadores e agentes novos devem
ler esta seção para entender o estado atual do contrato.

### 18.1 `runner.metrics` reservado ao Orchestrator

Telemetria de runners externos (Claude Code, Codex, Antigravity) é registrada
como evento `runner.metrics` no event store. **Nunca emitido por agentes** —
fica em `vocabulary.reserved_orchestrator_actions`. Payload mínimo: `runner_id`,
`task_id` (opcional), `metrics: { tokens_input, tokens_output, duration_ms,
model, session_id }`.

### 18.2 `prior_status="done"` em `issue.report`

`prior_status` enum agora aceita `"done"`, mas **apenas** quando
`action=issue.report`. As demais actions (claim/complete/review) são
bloqueadas pelos `const` no `allOf` do `agent_result.schema.json`. Permite
reportar problemas em tarefa imutável preservando evidência forense.

> Coercion: action=issue.report + task em done → prior_status DEVE ser 'done'.

### 18.3 Review por QA independente é o padrão

`RUNTIME_POLICY.yaml#review_authorization` defaulta para **`"qa_role"`**.
Implicações:

- `complete` continua exigindo `actor == assigned_to` (owner lock).
- `review` agora exige `runtime_policy.resolve_role(actor) ∈ {qa, orchestrator}`.
- Tentativa de owner reviewar sem role QA → `REVIEW_ROLE_VIOLATION`.

O service injeta `_reviewer_role` no payload do evento `review` após resolver
via `agents_swarm.yaml` ou heurística (`agent-qa*` → "qa").

### 18.4 `orchestrator.file.write` carrega metadata forense

Payload de `orchestrator.file.write` agora contém `effects[]` com:

```
{ "path": "...", "before_sha256": "...|null", "after_sha256": "...",
  "bytes": N, "encoding": "utf-8",
  "artifact_sha256": "...", "artifact_path": ".roadmap/artifacts/file-effects/<sha>.json" }
```

Artifacts content-addressed permitem replay/audit determinístico. Verificação
via `file_effects.verify_artifact()` detecta `ARTIFACT_MISSING`,
`ARTIFACT_HASH_MISMATCH`, `ARTIFACT_CONTENT_HASH_MISMATCH`.

### 18.5 Append serializável (`append_transactional`)

`service.submit/run` usam `_append_events_transactionally` que envolve
parse + revalidate + decide-seq + append + project sob o mesmo file lock
(`.roadmap/activity.jsonl.lock`). Rejeições:

- `STALE_STATE_SEQ` — `expected_first_seq` defasado.
- `STALE_STATE_HASH` — `expected_projection_hash` defasado.
- `STORE_LOCK_TIMEOUT` — lock não adquirido em `timeout`.

Concorrência multi-processo não produz duplicate `event_seq` (FIX-1806).

### 18.6 Atomic file effects (staging → append → commit)

`file_updates` passam por `.roadmap/staging/` antes do append. Sequência:

1. `stage_and_compute(root, file_updates)` → staged paths + metadata
2. `append_transactional(...)` persiste eventos
3. `commit_staged(root, staged)` aplica os arquivos finais via `os.replace`

Em qualquer falha (lock timeout, stale state, boundary violation) →
`discard_staged()` limpa o staging sem deixar arquivo final. Recover após
crash via `service.recover_file_effects()`.

### 18.7 Hotfix validado com códigos estruturados

`build_hotfix_event` agora chama `validate_hotfix_request` internamente
(M-03). Códigos:

| Código | Significado |
|---|---|
| `HOTFIX_ISSUE_NOT_FOUND` | issue_id ausente ou desconhecido |
| `HOTFIX_ISSUE_NOT_OPEN` | issue já resolved |
| `HOTFIX_TARGET_NOT_FOUND` | `fixes` aponta para task inexistente |
| `HOTFIX_TARGET_NOT_DONE` | target imutável-done não está done |
| `HOTFIX_SCOPE_INVALID` | `scope_patch` vazio/ausente |
| `HOTFIX_ALREADY_EXISTS` | duplicate hotfix para mesmo issue |

### 18.8 Baseline lessons reseed por evento

`service.init` emite `orchestrator.view.mutate(target=lessons, change=baseline_reseed)`
com `BASELINE_LESSONS` (LES-0001/2/3 completos). O projetor reconstrói
`lessons.json` por replay — não há mais edição manual do read model.

### 18.9 Plugin dispatch parity (`tasks_with_planned_plugins`)

`service.eligible` e `service.run` consomem o mesmo universo. Plugin tasks
não admitidas no event store são detectadas via `load_plugin_seeds` e
admitidas via `task.create` determinístico antes do claim.

### 18.10 Vocabulário canônico de reject codes

`src/esaa/reject_codes.py` é a fonte única dos códigos de erro
(`WORKFLOW_GATE_CODES`, `OPERATIONAL_CODES`, `HOTFIX_CODES`, `ALL_CODES`).
Inventory test (`tests/test_reject_codes_inventory.py`) garante que todo
`ESAAError(code, ...)` emitido no engine tem código registrado.
