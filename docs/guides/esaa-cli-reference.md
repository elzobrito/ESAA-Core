# ESAA — Referência do CLI

🌐 **Português** · [English](esaa-cli-reference.en.md)

Referência de todos os subcomandos de `esaa` (pacote `esaa-core`, linha
0.5.0b10). Sintaxes extraídas do `--help` real do CLI.

**Flags globais** (antes do subcomando):

```text
esaa [--root ROOT] [--runner RUNNER] [--version] <subcomando> ...
```

- `--root` — raiz do workspace (pasta que contém `.roadmap/`). Default: `.`.
- `--runner` — identidade do runner carimbada em todo evento (G08); pode vir
  de `ESAA_RUNNER_ID`. Ex.: `codex`, `claude-code`.

Quase todas as transições aceitam `--dry-run`: simulam o evento, validam
contra schema e mostram o hash resultante **sem persistir**.

Para comandos que escrevem eventos (`init`, `task create`, `claim`, `complete`,
`review`, `submit`, `issue`, `hotfix`, `activity`, `run`, `runner metrics`),
informe `--runner <id>` antes do subcomando ou configure `ESAA_RUNNER_ID`.

---

## Workspace e estado canônico

### `bootstrap` — instalar templates de governança

```text
esaa bootstrap [--profile {public,production}] [--force]
```

Instala os contratos, schemas e policies empacotados em `.roadmap/`.
`public` é o perfil padrão; `production` é a variante endurecida.

### `init` — inicializar estado limpo

```text
esaa init [--run-id RUN_ID] [--master-correlation-id ID] [--force]
```

Cria o event store e as projeções; emite o reseed das lessons baseline
(LES-0001/2/3) por evento, nunca por edição manual.

### `project` — reprojetar read models

```text
esaa project
```

Reconstrói `roadmap.json`, `issues.json`, `lessons.json` deterministicamente a
partir de `activity.jsonl`.

### `verify` — checar consistência

```text
esaa verify [--chain]
```

Reprojeta e compara o hash SHA-256 da projeção canonicalizada →
`ok | mismatch | corrupted`. Com `--chain`, valida também a hash chain do
event store.

### `replay` — reconstruir estado em um ponto

```text
esaa replay [--until EVENT_SEQ|EVENT_ID] [--no-write]
```

Reconstrói o estado até o evento indicado. `--no-write` calcula sem gravar as
views — útil para auditoria histórica.

### `chain init` — ancorar hash chain

```text
esaa chain init [--force]
```

Adiciona um evento `chain.anchor` que ancora a cadeia de hashes do event store.
Use `--force` apenas quando precisar recriar a âncora de forma explícita.

### `snapshot` — checkpoint e compactação

```text
esaa snapshot --before N [--compact] [--dry-run]
```

Grava um checkpoint das projeções cobrindo eventos com `event_seq <= N`.
`--compact` arquiva os eventos incluídos ao lado do snapshot, mantendo o
replay auditável sem o event store crescer indefinidamente.

### `activity clear` — reiniciar event store

```text
esaa activity clear [--force] [--dry-run] [--backup-dir DIR]
```

Faz backup e limpa `.roadmap/activity.jsonl`. Use `--dry-run` para inspecionar
o plano e `--force` para truncar de fato. Operação administrativa e destrutiva:
rode `verify` antes e depois.

---

## Planejamento e despacho

### `task create` — criar tarefa

```text
esaa task create TASK_ID --kind {spec,impl,qa} --title TITLE
  [--description D] [--output PATH]... [--depends-on TASK]...
  [--target T]... [--boundary-grant FNMATCH] [--dry-run]
```

Apenda um `task.create` do Orchestrator. `--boundary-grant` concede um padrão
extra de escrita só para essa tarefa (autoridade do operador, T-2070).

### `eligible` — o que pode rodar agora

```text
esaa eligible
```

Lista tarefas com dependências satisfeitas e os `parallel_groups` (grupos
despacháveis em paralelo sem conflito de escrita).

### `state` — estado de uma tarefa

```text
esaa state TASK_ID
```

Mostra o status determinístico e a **próxima action esperada** — elimina o
"adivinhar se é claim ou complete".

### `dispatch-context` — contexto mínimo para o agente

```text
esaa dispatch-context TASK_ID
```

Retorna o pacote mínimo de despacho: tarefa, `expected_action`,
`allowed_actions`, slice do schema do envelope, lessons ativas aplicáveis e
`runtime_capabilities` (se registradas via `input commands`).

---

## Transições do ciclo

### `claim` — reivindicar (todo → in_progress)

```text
esaa claim TASK_ID --actor ACTOR [--notes NOTES] [--dry-run]
```

### `complete` — concluir (in_progress → review)

```text
esaa complete TASK_ID --actor ACTOR --check CHECK [--check ...]
  [--file-updates FILE.json|-] [--notes NOTES]
  [--issue-id ISS] [--fixes F] [--dry-run]
```

`--file-updates` recebe um arquivo JSON (ou stdin) com
`[{"path","content"}]` ou a forma compacta `edits` com `base_sha256`.
Os arquivos são aplicados pelo Orchestrator com staging atômico. `--check` é
obrigatório (mín. 1; hotfix exige 2). Quem completa deve ser quem reivindicou.

### `review` — revisar (review → done | in_progress)

```text
esaa review TASK_ID --actor ACTOR --decision {approve,request_changes}
  [--task TASKS] [--dry-run]
```

Exige ator com role QA (`review_authorization=qa_role`). `approve` torna a
tarefa `done` (terminal e imutável); `request_changes` devolve a
`in_progress`.

### `submit` — aplicar envelope agent.result

```text
esaa submit [FILE] --actor ACTOR [--dry-run]
```

Valida e aplica um envelope JSON completo (`activity_event` +
`file_updates`) produzido por um agente — o caminho usado por runners LLM.
Passa por todos os workflow gates (WG-001..005) e usa append transacional.

### `run` — orquestração automática

```text
esaa run [--steps N] [--parallel N] [--adapter {mock,http}]
  [--llm-url URL] [--llm-token TOKEN] [--llm-timeout S]
  [--until-done] [--dry-run]
```

Executa ondas de despacho: mock (testes/CI) ou HTTP (endpoint LLM).
`--until-done` roda até não restar tarefa elegível.

---

## Desvios, defeitos e lições

### `issue report` / `issue resolve`

```text
esaa issue report TASK_ID --actor ACTOR --issue-id ISS \
  --severity {low,medium,high,critical} --title TITLE \
  --symptom SYMPTOM --repro-step STEP [--repro-step STEP ...] \
  [--fixes TASK_ID] [--dry-run]

esaa issue resolve --issue-id ISS [--hotfix-task-id TASK_ID] [--dry-run]
```

Exemplo:

```powershell
esaa --runner codex issue report T-1000 --actor agent-qa `
  --issue-id ISS-1000-DOCS --severity medium `
  --title "Guia incompleto" `
  --symptom "Sintaxe do comando operacional esta incompleta" `
  --repro-step "Executar esaa issue report --help" `
  --fixes T-1000
```

`issue.report` é a saída fail-closed do agente bloqueado — exige
`evidence.symptom` + `evidence.repro_steps`. Única action que aceita
`prior_status="done"` (reportar bug em tarefa imutável).

### `hotfix create`

```text
esaa hotfix create --issue-id ISS --fixes TASK_ID \
  [--scope-patch PREFIX ...] [--dry-run]
```

Cria a tarefa de correção para defeito em task `done`: exige issue aberta,
referência à task original (que permanece intacta) e escopo declarado. O
`complete` da hotfix exige `issue_id`, `fixes` e 2+ checks. No core atual,
`hotfix create` gera uma tarefa `impl`; `scope_patch` restringe ainda mais a
escrita, mas não troca a boundary do `task_kind`. Para correções puramente
documentais, crie uma nova tarefa `spec` com `boundary-grant` quando necessário.

### `reject` — registrar output inválido

```text
esaa reject TASK_ID --error-code CODE --source-action ACTION
  --message MSG [--dry-run]
```

Apenda `output.rejected` com código canônico (`ACTION_COLLAPSE`,
`MISSING_CLAIM`, `PRIOR_STATUS_MISMATCH`, ...). Fonte única:
`src/esaa/reject_codes.py`.

### `vocabulary` — vocabulário do protocolo

```text
esaa vocabulary [--profile PROFILE]
```

Mostra os mapeamentos canônicos (actions, reject codes) — por perfil, se
indicado.

---

## Runners externos

### `input commands` — capacidades de comando por runner

```text
esaa input commands validate PATH
esaa input commands register PATH [--runner-id ID]
esaa input commands show [--runner-id ID]
```

Registra em `.roadmap/runner-inputs/commands/<runner-id>.yaml` o YAML de
capacidades (superfícies de shell, ferramentas, regras). **Local ao
workspace**, não canônico. Injetado no `dispatch-context` como
`runtime_capabilities`.

### `runner metrics` — telemetria de runner externo

```text
esaa runner metrics [--file FILE|-] \
  [--task-id TASK_ID] [--actor ACTOR] [--runner-id ID] \
  [--runner-kind KIND] [--model MODEL] [--command-surface SURFACE] \
  [--started-at ISO] [--ended-at ISO] [--latency-ms N] \
  [--input-tokens N] [--output-tokens N] [--total-tokens N] \
  [--cost-estimate N] [--status {success,failed,cancelled,unknown}] \
  [--error-code CODE] [--correlation-id ID] [--dry-run]
```

Na prática, informe pelo menos `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface` e `status` (ou passe um JSON com esses campos via `--file`).
Registra evidência de execução externa como evento `runner.metrics` — reservado
ao Orchestrator/operador, nunca emitido por agentes.

### `metrics` — métricas do runtime

```text
esaa metrics
```

Emite métricas estruturadas do estado atual do workspace.

---

## Plugins e roadmaps externos

### `plugin`

```text
esaa plugin list | new | validate | doctor | install | remove | status
```

Ciclo de vida de pacotes de roadmap/inputs: scaffold (`new`), validação,
diagnóstico (`doctor`), instalação e remoção no workspace.

### `roadmap`

```text
esaa roadmap list | status | activate | pause | resume | deactivate
```

Controla execuções de roadmaps de plugin. Instalar **não** ativa: a ativação é
um passo explícito — evita tornar tarefas executáveis por acidente.

### `plugin-status`

```text
esaa plugin-status [--detail] [--plugin ARQUIVO.json]
```

Compara planejado vs. projetado por plugin; `--detail` lista task a task.

---

## Integração e recuperação

### `process` — inbox de arquivos

```text
esaa process [--dry-run]
```

Processa arquivos pendentes de `.roadmap/inbox/` (canal de entrada governado
por arquivo).

### `effects recover` — recuperar file effects

```text
esaa effects recover [--dry-run]
```

Reaplica efeitos de arquivo ausentes a partir dos artifacts forenses
(`.roadmap/artifacts/file-effects/`) — recuperação pós-crash do commit
atômico. Use `--dry-run` para listar o que seria reaplicado.

### `scenario hotfix` — trace demonstrável

```text
esaa scenario hotfix [--current] [--issue-id ISSUE_ID]
```

Executa o cenário operacional completo de hotfix (issue → hotfix → ciclo),
útil para validar o protocolo ponta a ponta. Sem `--current`, o cenário usa um
workspace temporário; com `--current`, opera no workspace atual.

---

## Veja também

- [Cenários práticos (cookbook)](esaa-cenarios.md)
- [Primeiros passos](esaa-getting-started.md)
- [Operando Codex e Claude Code como runners](esaa-runners-codex-claude-code.md)
- [Por que usar o ESAA](esaa-why.md)
