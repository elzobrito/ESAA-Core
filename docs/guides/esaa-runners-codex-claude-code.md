# Operando Codex e Claude Code como runners do ESAA

O ESAA não usa MCP. Runners LLM (Codex, Claude Code, Antigravity, etc.)
integram-se por **CLI local + arquivos**: leem o contexto que o Orchestrator
expõe, produzem um envelope `agent.result` e o submetem ao gate. Este guia
mostra o fluxo completo e as regras que evitam rejeição.

## Papéis

- **Runner** — o software que executa o LLM (Codex CLI, Claude Code). Carimba
  provenance (`--runner`) e telemetria (`runner metrics`).
- **Agente** — a identidade lógica que assina as transições (`--actor`), ex.:
  `agent-spec`, `agent-impl`, `agent-qa`. Um runner pode operar vários agentes,
  mas **quem completa deve ser quem reivindicou** (WG-004).
- **Orchestrator** — o CLI `esaa`: único escritor do event store, valida tudo
  antes de persistir.

## 1. Identidade do runner (provenance, G08)

Todo comando que escreve evento deve carimbar quem executa:

```powershell
esaa --root <workspace> --runner codex <subcomando> ...
esaa --root <workspace> --runner claude-code <subcomando> ...
# ou uma vez por sessão:
$env:ESAA_RUNNER_ID = "codex"
```

A identidade fica gravada em cada evento — auditoria de *quem* fez *o quê*.
Nos exemplos abaixo, se `ESAA_RUNNER_ID` não estiver definido, mantenha
`--runner <id>` em cada comando que persiste eventos.

## 2. Registrar capacidades do ambiente (`input commands`)

Resolve o problema clássico "o agente não sabe se pode usar PowerShell, WSL,
grep, sed". Uma vez **por workspace**:

```powershell
esaa --root <workspace> --runner codex input commands register `
  docs/operations/runtime-capabilities.windows-wsl.yaml
esaa --root <workspace> --runner codex input commands show
```

O YAML declara `command_surfaces` (powershell, cmd, wsl_ubuntu, ...),
`available_tools`, ferramentas verificadas no WSL e
`recommended_agent_rules`. Fica em
`.roadmap/runner-inputs/commands/<runner-id>.yaml` — **local ao workspace**
(não é global da instalação) e não-canônico (não entra no event store). O
conteúdo é injetado no `dispatch-context` como `runtime_capabilities`.

## 3. Obter o contexto mínimo da tarefa

```powershell
esaa eligible                        # o que pode rodar agora
esaa dispatch-context T-EXEMPLO      # pacote de despacho de uma tarefa
```

O `dispatch-context` traz tudo que o prompt do agente precisa — e nada além:

- `task` (id, kind, status, descrição, outputs, depends_on)
- `expected_action` e `allowed_actions` (ex.: `claim` + `issue.report`)
- `schema_slice` — o recorte do `agent_result.schema.json` válido agora
- `lessons` ativas aplicáveis ao kind (constraints invioláveis)
- `runtime_capabilities` (se registradas)

## 4. O ciclo two-step

**Uma action por invocação** (LES-0001, gate WG-005). O runner invoca o agente
duas vezes por tarefa:

### Invocação 1 — claim (sinalização, sem trabalho técnico)

Via envelope:

```json
{"activity_event": {"action": "claim", "task_id": "T-EXEMPLO", "prior_status": "todo"}}
```

```powershell
esaa --runner claude-code submit claim.json --actor agent-spec
```

Ou pelo atalho determinístico (sem gastar chamada de LLM):

```powershell
esaa --runner claude-code claim T-EXEMPLO --actor agent-spec
```

### Invocação 2 — complete (trabalho + evidência + arquivos)

O agente produz o envelope completo:

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-EXEMPLO",
    "prior_status": "in_progress",
    "notes": "resumo do que foi produzido",
    "verification": {"checks": ["criterio 1 atendido", "criterio 2 atendido"]}
  },
  "file_updates": [
    {"path": "docs/spec/exemplo.md", "content": "<conteudo completo>"}
  ]
}
```

```powershell
esaa --runner claude-code submit complete.json --actor agent-spec
```

Regras do envelope (schema `additionalProperties: false`):

- **JSON puro** — sem markdown, sem cercas, sem texto solto.
- `prior_status` obrigatório e igual ao status injetado (WG-003).
- Campos como `event_seq`, `ts`, `actor`, `assigned_to` são **proibidos** —
  o Orchestrator os gera.
- `file_updates` só com `action=complete` (WG-002); paths dentro das
  boundaries do `task_kind` (`spec`→`docs/**`; `impl`→`src/**`,`tests/**`;
  `qa`→`docs/qa/**`,`tests/**`).
- Forma compacta: `file_updates.edits` com `base_sha256` — patch pequeno que
  falha se o arquivo base mudou (economiza tokens e evita sobrescrita cega).
- Os arquivos são aplicados pelo **Orchestrator** com staging atômico; o
  agente nunca escreve direto no repositório.

### Invocação 3 — review por QA independente

```powershell
esaa --runner claude-code review T-EXEMPLO --actor agent-qa --decision approve
```

`review_authorization=qa_role`: o owner não se auto-aprova
(`REVIEW_ROLE_VIOLATION`). `request_changes` devolve a tarefa para
`in_progress`.

### Quando bloqueado: `issue.report`

Fail-closed — se faltar dependência, contexto ou boundary, o agente emite:

```json
{
  "activity_event": {
    "action": "issue.report",
    "task_id": "T-EXEMPLO",
    "prior_status": "in_progress",
    "issue_id": "ISS-0001",
    "severity": "high",
    "title": "Dependencia X nao esta done",
    "evidence": {"symptom": "...", "repro_steps": ["passo 1", "passo 2"]}
  }
}
```

## 5. Os 5 workflow gates (por que outputs são rejeitados)

| Gate | Verifica | Reject code |
|---|---|---|
| WG-001 | `complete`/`review` só após `claim` | `MISSING_CLAIM` |
| WG-002 | `complete` exige checks; `file_updates` exige `complete` | `MISSING_VERIFICATION` / `MISSING_COMPLETE` |
| WG-003 | `prior_status` bate com o roadmap | `PRIOR_STATUS_MISMATCH` |
| WG-004 | Quem completa é quem reivindicou | `LOCK_VIOLATION` |
| WG-005 | Uma action por output | `ACTION_COLLAPSE` |

`PRIOR_STATUS_MISMATCH` é a única rejeição que **não** consome tentativa
(tratada como lag de contexto). Limites: 3 tentativas por tarefa, cooldown de
2 min, TTL de 30 min por attempt.

## 6. Telemetria do runner

Após cada execução externa, o operador/harness registra evidência:

```powershell
esaa --runner codex runner metrics `
  --task-id T-EXEMPLO `
  --actor agent-spec `
  --runner-id codex `
  --runner-kind codex `
  --model gpt-5 `
  --command-surface "powershell: python -m esaa submit" `
  --latency-ms 1250 `
  --input-tokens 4200 `
  --output-tokens 900 `
  --status success `
  --correlation-id CID-T-EXEMPLO
```

Vira evento `runner.metrics` (reservado ao Orchestrator — agentes nunca o
emitem), dando telemetria real sem depender do provedor do modelo. Campos
obrigatórios: `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface` e `status`.

## 7. Receitas práticas

### Codex / Claude Code como operador interativo

1. `esaa --runner codex eligible` → escolher tarefa.
2. `esaa --runner codex dispatch-context T-X` → montar o prompt do agente.
3. Agente responde **só o envelope JSON** → salvar em arquivo.
4. `esaa --runner codex submit envelope.json --actor agent-<kind>` (usar
   `--dry-run` antes, se quiser validar sem persistir).
5. Repetir para o complete; despachar `agent-qa` para o review.
6. `esaa --runner codex verify` ao final de cada onda.

### Transições determinísticas sem LLM

Para passos que não exigem raciocínio (claim, review de rotina, task create),
use os comandos diretos (`claim`, `review`, `task create`) — zero tokens.

### Instrução de sistema recomendada para o agente

O arquivo `CLAUDE.md`/`AGENTS.md` do projeto deve refletir o
`AGENT_CONTRACT.yaml`: uma action por invocação, `prior_status` sempre
presente, `file_updates` só com complete, nunca tocar em `done`, na dúvida
`issue.report`. Em divergência, os artefatos canônicos em `.roadmap/`
prevalecem.

## Veja também

- [Primeiros passos](esaa-getting-started.md)
- [Referência do CLI](esaa-cli-reference.md)
- [Por que usar o ESAA](esaa-why.md)
