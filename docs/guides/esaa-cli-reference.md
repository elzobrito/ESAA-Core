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
esaa bootstrap [--profile {public,production}] [--force] [--preserve-guides | --merge-guides]
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
  [--target T]... [--task-type TYPE]
  [--acceptance-criterion TEXT]...
  [--required-review-mode MODE]
  [--supersedes TASK]...
  [--boundary-grant FNMATCH] [--dry-run]
```

Apenda um `task.create` do Orchestrator. `--boundary-grant` concede um padrão
extra de escrita só para essa tarefa (autoridade do operador, T-2070).

Campos G07 opcionais:

- `--task-type`: intenção operacional (`feature`, `hotfix`, `audit`, `release`,
  `memory`, `governance`, `maintenance`). `--kind` continua controlando ator e
  boundary.
- `--acceptance-criterion`: critério de aceite ordenado; pode ser repetido.
- `--required-review-mode`: exige review tipado (`functional`, `security`,
  `regression`, `docs`, `governance`, `release`).
- `--supersedes`: declara que a nova tarefa substitui uma tarefa existente.
  `superseded_by` é derivado pelo projector, é somente leitura e não altera o
  status da tarefa substituída.

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
  [--review-mode MODE] [--task TASKS] [--dry-run]
```

Exige ator com role QA (`review_authorization=qa_role`). `approve` torna a
tarefa `done` (terminal e imutável); `request_changes` devolve a
`in_progress`. Se a tarefa possui `required_review_mode`, todo review deve
informar `--review-mode` igual, inclusive `request_changes`. Reviews com modo
ausente, inválido ou divergente falham antes de append no `activity.jsonl`.

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

### Lessons G07

Lessons aceitam `status` `active`, `experimental`, `superseded` ou `archived`.
`active` e `experimental` podem aparecer no `dispatch-context`; `superseded` e
`archived` ficam consultáveis, mas fora do contexto ativo.

O filtro combina valores da mesma dimensão com OR e dimensões diferentes com
AND. As dimensões são `task_kinds`, `task_types`, `review_modes`, `paths`,
`actors` e `runners`. O contrato novo usa `enforcement` como objeto:

```json
{
  "enforcement": {
    "mode": "require_review_mode",
    "value": "governance"
  }
}
```

Shapes legados com `applies_to` continuam aceitos e são normalizados
internamente quando necessário. `require_boundary_grant` nunca amplia
permissões; ele apenas exige um grant explícito já existente.

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

## Arquitetura e operações do runtime

Esta referência concentra detalhes antes incluídos no README raiz. Carregue o
tópico pertinente; os contratos instalados regem o workspace, inclusive quando
seus templates diferirem dos publicados pelo pacote.

### Autoridade, estados e contexto

```text
Agent proposes -> Orchestrator validates -> Event store records -> Projection updates

todo --claim--> in_progress --complete--> review --approve--> done
                    ^                      |
                    +--- request_changes --+
```

Agentes emitem claim, complete, review ou issue.report. Criação de tarefas,
resolução de issues, proveniência, métricas, escrita de arquivos e materialização
são operações do Orchestrator. As listas exatas estão nos contratos e schemas.
O harness executa agentes; não substitui a governança ESAA.

O contexto mínimo usa schema_slice por ação, lessons/issues filtradas e interfaces
de dependências concluídas, sem carregar seus corpos. Comandos determinísticos
e edits exatos evitam payload repetido; isso não equivale a redução de custo de
inferência comprovada sem medir tokens reais. Veja o guia de runners para envelopes,
CRLF, UTF-8, base_sha256, limites de checks e autorização de review.

A resolução de papel usa agents_swarm e os fallbacks do runtime. A política
review_authorization controla quem revisa; a atribuição do complete continua
vinculada ao actor que reivindicou. Não altere a política para contornar uma revisão.

### Fontes versionadas

Estes exemplos pertencem ao código e ao bundle de governança versionados.

```text
.roadmap/AGENT_CONTRACT.yaml
.roadmap/ORCHESTRATOR_CONTRACT.yaml
.roadmap/RUNTIME_POLICY.yaml
.roadmap/STORAGE_POLICY.yaml
.roadmap/PROJECTION_SPEC.md
.roadmap/agent_result.schema.json
src/esaa/
tests/
```

### Caminhos criados por operações

Estes caminhos podem estar ausentes em um workspace limpo; surgem na operação correspondente. Documentos de tarefas entram pelo fluxo governado.

```text
.roadmap/plugins.lock.json
.roadmap/roadmaps.lock.json
.roadmap/plugin-inputs/
.roadmap/snapshots/
docs/spec/
docs/qa/
```

### Organização e projeções

Contratos, schemas, políticas de armazenamento/runtime, PROJECTION_SPEC e perfis
PARCER ficam em `.roadmap/`; o código está em `src/esaa/` e testes em `tests/`.
Documentos de tarefa ficam em `docs/spec/` e `docs/qa/`. O README raiz é uma exceção
explícita de escrita para spec no contrato padrão. Boundaries ativos prevalecem.

O replay reconstrói roadmap, issues, lessons e perfil do projeto a partir de eventos.
`verify` compara as projeções: `ok` confirma consistência; `mismatch` indica diferença;
`corrupted` indica histórico inválido; `unknown` não estabelece verificação.
Uma tarefa planejada sem eventos de ciclo não é, por si só, divergência.
Nunca corrija uma projeção por edição manual.

As lessons baseline são semeadas por evento e sobrevivem a project/replay.
Condições históricas não devem virar instruções globais: respeite escopo e modo de
enforcement de cada lesson. Termos antigos como promote, phase.complete, backlog e
ready podem ser históricos ou de outro perfil; consulte `esaa vocabulary --help`.

### Plugins e execuções

Instalação grava `.roadmap/plugins.lock.json`; ativação grava
`.roadmap/roadmaps.lock.json` e torna tarefas elegíveis. Não confunda pacote disponível,
instalado e execução ativa. Pause oculta a execução de eligible; deactivation encerra
seu uso para novo planejamento, sem ser sinônimo de uninstall.

```bash
python -m esaa --runner codex plugin install ./security
python -m esaa --runner codex roadmap activate security --execution-id default
python -m esaa eligible
```

IDs seguem `<plugin-id>-<execution-id>-<local-task-id>`: `security-default-T-001`.
Templates `.template.json` não são executáveis por si só. Roadmaps soltos são
compatibilidade legada. Catálogos externos usam ESAA_PLUGINS_HOME ou `~/.esaa/plugins`,
com estrutura `<plugin>/<version>/plugin.json`. Um pacote pode não incluir plugins
bundled; diretórios locais continuam instaláveis. Entradas copiadas ficam em
`.roadmap/plugin-inputs/`. Consulte os guias de plugins para autoria e ciclo completo.

### Onboarding e guias distribuídos

O bootstrap instala contratos e orientações portáteis. O README do consumidor não
é cópia do README do Core. AGENTS aponta para arquivos locais instalados; o guia
Claude aponta para ../AGENTS.md. Nenhuma leitura do manual inteiro é necessária.

No padrão, conflitos são rejeitados. `--preserve-guides` conserva os guias existentes;
`--merge-guides` conserva a região do projeto e atualiza a região ESAA;
`--force` permite sobrescrever os destinos autorizados. Contratos existentes ainda
exigem force para atualização. Preserve/merge são mutuamente exclusivos. Markers
inválidos impedem merge antes de escrita de governança. Um CLAUDE.md na raiz não é
mesclado como se fosse .claude/CLAUDE.md. Histórico, projeções, backups e snapshots
não são substituídos pelo bootstrap. Workspaces existentes não migram automaticamente.

```bash
python -m esaa --runner codex onboard --answers project-profile.json --dry-run
python -m esaa profile show
```

O onboarding registra como se dirigir ao operador, deriva perfil do projeto e cria
uma cadeia governada. Seeds pendentes podem ser substituídos por tarefas específicas;
init limpo começa sem demos, e `--with-demo-tasks` é explícito.

### Concorrência e efeitos transacionais

`run --parallel` agrupa tarefas independentes, mantendo append serializado.
Conflitos consideram paths exatos, prefixos de diretório, scope_patch e efeitos
reais da onda. O lock do store não autoriza edições concorrentes nos mesmos arquivos.

```text
stage_and_compute -> append_transactional -> commit_staged
```

```json
{
  "task_id": "T-EXAMPLE",
  "files": ["src/example.py"],
  "effects": [{
    "path": "src/example.py",
    "before_sha256": null,
    "after_sha256": "<sha>",
    "bytes": 10,
    "encoding": "utf-8",
    "artifact_sha256": "<sha>",
    "artifact_path": ".roadmap/artifacts/file-effects/<sha>.json"
  }]
}
```

O exemplo mostra metadados forenses de orchestrator.file.write. O artefato
endereçado por conteúdo permite auditoria/replay. A transação relê eventos sob lock,
confere sequência/hash esperados, materializa antes de persistir e verifica o append.
Erros incluem STORE_LOCK_TIMEOUT, STALE_STATE_SEQ, STALE_STATE_HASH e
APPEND_VERIFY_FAILED. Falhas não autorizam remoção manual do lock ou edição do store.

Efeitos admitidos que não chegaram ao commit podem ser recuperados; staging órfão
é limpo pelo runtime. Verificação de artefatos detecta ARTIFACT_MISSING,
ARTIFACT_HASH_MISMATCH e ARTIFACT_CONTENT_HASH_MISMATCH. Detalhes de implementação
estão em store.py e file_effects.py; os agentes não devem reproduzir essa transação.

### Hotfix, snapshots e recuperação

```text
issue.report -> hotfix.create -> claim -> complete -> review(approve) -> issue.resolve
```

Hotfix exige issue_id, fixes, scope_patch e dois checks no complete. Erros de pedido:
HOTFIX_ISSUE_NOT_FOUND, HOTFIX_ISSUE_NOT_OPEN, HOTFIX_TARGET_NOT_FOUND,
HOTFIX_TARGET_NOT_DONE, HOTFIX_SCOPE_INVALID e HOTFIX_ALREADY_EXISTS.
O cenário hotfix padrão usa workspace temporário; `--current` altera o workspace real.

```bash
python -m esaa snapshot --before 100 --compact --dry-run
python -m esaa replay --no-write
python -m esaa effects recover --help
```

Snapshots capturam estado e evidência de replay. Compaction produz snapshot, archive,
tail e manifest; exige estado verificado, projeções consistentes e corte dentro do
último evento verificado. Ausência de archive/tail invalida a recuperação.
Limpar histórico com `activity clear --force` é operação administrativa destrutiva,
ainda que crie backup; só executar quando explicitamente autorizado. Use dry-run
quando disponível e não confunda recuperação com autorização para apagar histórico.

### Runners e telemetria

Runners externos não precisam de adaptadores nativos de cada provedor. O adaptador
HTTP genérico recebe contexto e retorna envelope; token opcional vem de ESAA_LLM_TOKEN.

```bash
ESAA_LLM_URL=http://127.0.0.1:8080/agent python -m esaa --runner codex run --adapter http --steps 2
```

runner.metrics registra latência, runner, modelo, superfície de comando, status,
correlação e contagens reais conhecidas. Dados desconhecidos ficam ausentes ou null,
sem inventar custos. Um CLI determinístico não elimina o julgamento de uma revisão.
O vocabulário de erros do Core é centralizado em src/esaa/reject_codes.py.
