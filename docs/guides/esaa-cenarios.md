# ESAA — Cenários práticos (cookbook)

🌐 **Português** · [English](esaa-cenarios.en.md)

Este guia documenta os comandos do `esaa` (pacote `esaa-core`, linha 0.5.0b9)
**dentro de situações reais**, não como uma lista de flags. Cada cenário tem um
objetivo, os comandos na ordem em que você os usaria, a saída esperada e as
armadilhas. Para a sintaxe exaustiva de cada subcomando, veja a
[Referência do CLI](esaa-cli-reference.md); para o caminho mais curto, os
[Primeiros passos](esaa-getting-started.md).

> Convenções: os exemplos usam PowerShell (continuação de linha com `` ` ``).
> No bash/zsh troque `` ` `` por `\`. Todo comando que **escreve evento** carimba
> a identidade do runner — use `--runner <id>` antes do subcomando ou exporte
> `ESAA_RUNNER_ID`. O comando real é `esaa` (equivalente a `python -m esaa`).

## Personas e autoridade

Antes dos cenários, fixe quem faz o quê — isso explica por que certos comandos
exigem um `--actor` específico:

| Persona | Papel | O que emite |
|---|---|---|
| **Operador** / Orchestrator | Single writer do event store | `task create`, `hotfix create`, `issue resolve`, `reject`, `runner metrics`, plugins/roadmaps |
| **agent-spec / agent-impl** | Agentes executores | `claim`, `complete`, `issue report` |
| **agent-qa** | Revisor independente | `review` (único que pode aprovar) |

O agente **nunca** escreve direto em `.roadmap/`. Ele emite intenções; o
Orchestrator valida nos gates (WG-001..005) e persiste. Tudo vive em
`.roadmap/` e nada ali deve ser editado à mão.

---

## Índice de cenários

1. [Subir um workspace do zero](#cenário-1--subir-um-workspace-do-zero)
2. [Planejar um épico (tríade spec→impl→qa)](#cenário-2--planejar-um-épico-spec--impl--qa)
3. [Descobrir o que rodar agora](#cenário-3--descobrir-o-que-rodar-agora)
4. [Rodar o ciclo governado à mão](#cenário-4--rodar-o-ciclo-governado-à-mão)
5. [Concluir com `edits` em vez de `content`](#cenário-5--concluir-com-edits-em-vez-de-content)
6. [Aplicar um envelope de agente LLM (`submit`)](#cenário-6--aplicar-um-envelope-de-agente-llm-submit)
7. [Orquestração automática (`run`)](#cenário-7--orquestração-automática-run)
8. [Agente bloqueado: `issue report`](#cenário-8--agente-bloqueado-issue-report-fail-closed)
9. [Defeito em tarefa `done`: hotfix](#cenário-9--defeito-em-tarefa-done-o-fluxo-de-hotfix)
10. [Rejeitar um output inválido (`reject`)](#cenário-10--rejeitar-um-output-inválido)
11. [Usar um plugin de roadmap](#cenário-11--usar-um-plugin-de-roadmap)
12. [Criar e publicar o seu próprio plugin](#cenário-12--criar-e-publicar-o-seu-próprio-plugin)
13. [Registrar capacidades de um runner](#cenário-13--registrar-as-capacidades-de-um-runner)
14. [Telemetria de runner externo](#cenário-14--telemetria-de-runner-externo)
15. [Auditoria e integridade](#cenário-15--auditoria-e-integridade)
16. [Manutenção do event store](#cenário-16--manutenção-do-event-store)
17. [Concorrência e identidade de runner](#cenário-17--concorrência-e-identidade-de-runner)
18. [Operar runners reais: Claude Code, Codex, Gemini CLI, Grok](#cenário-18--operar-runners-reais-claude-code-codex-gemini-cli-grok)
19. [Tarefas com runners diferentes (workflow heterogêneo)](#cenário-19--tarefas-com-runners-diferentes-workflow-heterogêneo)
20. [Por que o event store não corrompe sob concorrência](#cenário-20--por-que-o-event-store-não-corrompe-sob-concorrência)

No fim há uma [referência rápida comando → cenário](#referência-rápida-comando--cenário)
e um [mapa de troubleshooting](#mapa-de-troubleshooting).

---

## Cenário 1 — Subir um workspace do zero

**Situação:** você acabou de instalar o `esaa-core` e quer transformar a pasta do
projeto num workspace governado, com o event store e as projeções limpos.

```powershell
pip install esaa-core
esaa --version
# esaa 0.5.0b9 (protocol 0.4.1, esaa 0.4.x)

# Identidade do runner para toda a sessão (evita repetir --runner)
$env:ESAA_RUNNER_ID = "claude-code"

# 1) Instalar os contratos/schemas/policies empacotados em .roadmap/
esaa bootstrap --profile public

# 2) Criar o estado canônico limpo (event store + projeções + lessons baseline)
esaa init

# 3) Conferir que projeção e event store estão consistentes
esaa verify
```

O que cada passo faz:

- `bootstrap --profile public` materializa `AGENT_CONTRACT.yaml`,
  `ORCHESTRATOR_CONTRACT.yaml`, os schemas e as policies. Use
  `--profile production` para a variante endurecida e `--force` para
  sobrescrever um bootstrap anterior.
- `init` emite os eventos de inicialização, cria `.roadmap/activity.jsonl`
  (a verdade histórica) e reprojeta `roadmap.json`, `issues.json` e
  `lessons.json` — incluindo o reseed das lessons baseline **LES-0001/2/3**.
  `--run-id` e `--master-correlation-id` correlacionam essa inicialização; use
  `--force` apenas para reinicializar um workspace existente.
- `verify` reprojeta a partir do event store e compara o hash SHA-256 da
  projeção canonicalizada. Saída esperada: `"verify_status": "ok"`. Qualquer
  `mismatch`/`corrupted` faz o CLI sair com código 2.

> **Armadilha:** em workspace com policy strict, `init` e qualquer escrita falham
> com `RUNNER_UNKNOWN` se o runner não estiver no registro. Runners conhecidos:
> `claude-code`, `claude-cowork`, `codex`, `human-terminal`, `unattended`.

---

## Cenário 2 — Planejar um épico (spec → impl → qa)

**Situação:** você vai entregar um fluxo de login SSO. O ESAA modela trabalho em
**tríades**: uma tarefa de especificação, uma de implementação e uma de QA, com
dependências encadeadas. Quem cria tarefas é o **Orchestrator/operador**.

```powershell
esaa task create T-LOGIN-SPEC --kind spec `
  --title "Especificar fluxo de login" `
  --description "Documentar o fluxo de autenticacao SSO" `
  --output docs/spec/login.md `
  --target documentation

esaa task create T-LOGIN-IMPL --kind impl `
  --title "Implementar fluxo de login" `
  --depends-on T-LOGIN-SPEC `
  --output src/auth/login.php

esaa task create T-LOGIN-QA --kind qa `
  --title "Validar fluxo de login" `
  --depends-on T-LOGIN-IMPL `
  --output docs/qa/login.md
```

Pontos que decidem o resultado:

- `--kind` define a **boundary de escrita** da tarefa:
  - `spec` → pode escrever em `docs/**`
  - `impl` → `src/**`, `tests/**`
  - `qa` → `docs/qa/**`, `tests/**` (proibido tocar em `src/**`)
- `--depends-on` é repetível e cria o encadeamento: `IMPL` só fica elegível
  quando `SPEC` chega a `done`, e `QA` depois de `IMPL`.
- `--output` (repetível) declara os arquivos esperados; `--target` (repetível)
  é um rótulo de objetivo. `--boundary-grant <fnmatch>` concede um padrão extra
  de escrita **só para aquela tarefa** (autoridade do operador, T-2070) — por
  exemplo, uma tarefa `spec` que precisa também gerar um `sql/seed.sql`.
- `--dry-run` simula o evento, valida contra o schema e mostra o hash resultante
  **sem persistir** — disponível em quase toda transição. Use para revisar antes
  de gravar.

---

## Cenário 3 — Descobrir o que rodar agora

**Situação:** o backlog tem dezenas de tarefas. Você quer saber, sem adivinhar,
o que está desbloqueado e o que pode rodar em paralelo.

```powershell
# Tudo que está elegível + grupos paralelizáveis sem conflito de escrita
esaa eligible
```

```jsonc
{
  "last_event_seq": 12,
  "eligible_count": 1,
  "max_parallel": 1,
  "eligible": ["T-LOGIN-SPEC"],
  "parallel_groups": [["T-LOGIN-SPEC"]]
}
```

`T-LOGIN-IMPL` e `T-LOGIN-QA` **não** aparecem ainda: dependem de tarefas que não
estão `done`. Para inspecionar uma tarefa específica e saber a **próxima action
esperada** (acaba com o "é claim ou complete?"):

```powershell
esaa state T-LOGIN-SPEC
# -> status: todo | expected_action: claim

# Pacote mínimo para despachar a tarefa a um agente
esaa dispatch-context T-LOGIN-SPEC
```

`dispatch-context` devolve: a tarefa, `expected_action`, `allowed_actions`, o
slice do schema do envelope, as lessons ativas aplicáveis e — se você registrou
capacidades via `input commands` (Cenário 13) — `runtime_capabilities`. É
exatamente o que você cola no prompt de um runner LLM.

---

## Cenário 4 — Rodar o ciclo governado à mão

**Situação:** você vai executar a tarefa de spec manualmente, sem adapter
automático. O protocolo exige **uma action por invocação** (LES-0001): não dá
para colapsar `claim` + `complete`.

```powershell
# Invocação 1 — reivindicar (todo -> in_progress)
esaa claim T-LOGIN-SPEC --actor agent-spec

# (produza o conteúdo do arquivo num JSON de file-updates)
#   updates.json:
#   [{ "path": "docs/spec/login.md", "content": "# Login SSO\n..." }]

# Invocação 2 — concluir com evidência + arquivos (in_progress -> review)
esaa complete T-LOGIN-SPEC --actor agent-spec `
  --check "docs/spec/login.md cobre os 3 fluxos exigidos" `
  --file-updates updates.json `
  --notes "Especificacao do fluxo de login"

# Invocação 3 — revisão por QA independente (review -> done | in_progress)
esaa review T-LOGIN-SPEC --actor agent-qa --decision approve
```

Regras que o gate aplica:

- **WG-001:** `complete`/`review` exigem um `claim` prévio (`MISSING_CLAIM`).
- **WG-004:** quem completa tem de ser quem reivindicou — `assigned_to == actor`,
  senão `LOCK_VIOLATION`.
- `--check` é repetível e **obrigatório**: mínimo 1 para `spec`/`impl`/`qa`,
  **2 para hotfix**. É a verificação registrada como evidência.
- `--file-updates` recebe um arquivo JSON (ou `-` para stdin). Os arquivos são
  aplicados **pelo Orchestrator**, com staging atômico em `.roadmap/staging/` —
  o agente nunca grava o efeito final.
- `review` exige ator com **role QA** (`review_authorization=qa_role`); o autor
  não se auto-aprova. `--decision request_changes` devolve a tarefa para
  `in_progress`; `approve` a torna `done` (terminal e imutável).

> **Dica:** rode cada passo com `--dry-run` primeiro para ver o hash e validar o
> envelope antes de persistir.

---

## Cenário 5 — Concluir com `edits` em vez de `content`

**Situação:** a tarefa `impl` precisa alterar um arquivo grande já existente. Em
vez de reenviar o arquivo inteiro, você envia **edits cirúrgicos** ancorados no
hash atual — o que rejeita patch sobre arquivo desatualizado.

`updates.json`:

```json
[
  {
    "path": "src/esaa/service.py",
    "base_sha256": "0123...def",
    "edits": [
      { "old_string": "texto antigo exato", "new_string": "texto novo", "replace_all": false }
    ]
  }
]
```

```powershell
esaa complete T-LOGIN-IMPL --actor agent-impl `
  --check "login.php implementa o fluxo da spec" `
  --check "tests/auth/login_test.php passa" `
  --file-updates updates.json
```

Semântica que evita corromper o arquivo:

- `base_sha256` é o SHA-256 dos **bytes atuais** do arquivo. Se mudou desde a
  leitura → `EDIT_BASE_MISMATCH`.
- `old_string` casa contra o texto UTF-8 com os newlines exatos do arquivo
  (**CRLF incluído — não normalize `\r\n` para `\n`**). Arquivo não-UTF-8 →
  `EDIT_INVALID`.
- Mais de um match exige `replace_all=true`, senão `EDIT_AMBIGUOUS`. Nenhum
  match → `EDIT_TARGET_NOT_FOUND`.
- O Orchestrator resolve `{path, base_sha256, edits}` para `{path, content}`
  **antes** dos external effects, dos resource limits, do staging e dos
  artifacts. O resultado é idêntico ao do formato `content`.

---

## Cenário 6 — Aplicar um envelope de agente LLM (`submit`)

**Situação:** um runner LLM (Codex, Claude Code) produziu o envelope completo —
`activity_event` + `file_updates` — em JSON. Você quer validá-lo e aplicá-lo
passando por todos os gates de uma vez.

`output.json` (exatamente **uma** `activity_event`):

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-LOGIN-SPEC",
    "prior_status": "in_progress",
    "notes": "Especificacao concluida",
    "verification": { "checks": ["spec cobre os 3 fluxos"] }
  },
  "file_updates": [
    { "path": "docs/spec/login.md", "content": "# Login SSO\n..." }
  ]
}
```

```powershell
# Validar sem persistir (recomendado antes de aplicar)
esaa submit output.json --actor agent-spec --dry-run

# Aplicar de verdade (ou via stdin: cat output.json | esaa submit - --actor agent-spec)
esaa submit output.json --actor agent-spec
```

`submit` é o caminho dos runners LLM: um único envelope, append transacional,
todos os workflow gates. Regras que ele impõe:

- Exatamente **uma** `activity_event` por output (WG-005, `ACTION_COLLAPSE`).
- `file_updates` só com `action=complete` (WG-002, LES-0002).
- `prior_status` sempre presente e coerente com o estado real (WG-003,
  `PRIOR_STATUS_MISMATCH`, LES-0003).
- JSON puro, sem markdown nem texto fora do envelope.

> O agente **nunca** envia o campo `runner` — o Orchestrator o carimba a partir
> de `--runner`/`ESAA_RUNNER_ID`. Operar Codex/Claude Code como runners está
> detalhado em [esaa-runners-codex-claude-code.md](esaa-runners-codex-claude-code.md).

---

## Cenário 7 — Orquestração automática (`run`)

**Situação:** em vez de despachar tarefa a tarefa, você quer que o ESAA puxe
tarefas elegíveis e as execute via adapter — mock (testes/CI) ou um endpoint LLM.

```powershell
# Um passo, adapter mock (determinístico, ótimo para CI)
esaa run --steps 1

# Várias tarefas independentes por onda
esaa run --steps 5 --parallel 3

# Rodar até não restar tarefa elegível
esaa run --until-done

# Contra um endpoint LLM HTTP
esaa run --adapter http --llm-url https://meu-endpoint/v1 --until-done

# Plano sem efeitos
esaa run --steps 1 --dry-run
```

- `--steps N` limita as ondas; `--until-done` ignora `--steps` e roda até
  `eligible` ficar vazio.
- `--parallel N` despacha até N tarefas **sem conflito de escrita** por onda
  (os `parallel_groups` do Cenário 3).
- `--adapter http` usa `--llm-url`/`--llm-token`/`--llm-timeout` (ou as variáveis
  `ESAA_LLM_URL` etc.). `mock` é o default e não chama rede.

---

## Cenário 8 — Agente bloqueado: `issue report` (fail-closed)

**Situação:** no meio da execução o agente descobre que não tem como continuar —
dependência ausente, contexto insuficiente, boundary impossível. A saída correta
**não** é forçar um `complete`; é reportar uma issue com evidência.

```powershell
esaa issue report T-LOGIN-SPEC --actor agent-spec `
  --issue-id ISS-LOGIN-SPEC --severity medium `
  --title "Dependencia ausente" `
  --symptom "Nao ha contrato de callback no workspace" `
  --repro-step "Executar esaa dispatch-context T-LOGIN-SPEC" `
  --repro-step "Conferir que nao ha docs/spec/callback.md"
```

- `--severity` ∈ {`low`, `medium`, `high`, `critical`}.
- `--symptom` + `--repro-step` (repetível) são **obrigatórios**: a issue precisa
  ser reproduzível. Sem evidência, não há issue.
- `issue.report` é a **única** action que aceita `prior_status="done"` — é como
  você sinaliza um defeito numa tarefa imutável (leva ao Cenário 9).
- `--fixes T-XXXX` referencia a tarefa-alvo do defeito.

Quando o Orchestrator/operador endereça a issue:

```powershell
esaa issue resolve --issue-id ISS-LOGIN-SPEC --hotfix-task-id T-LOGIN-HOTFIX
```

---

## Cenário 9 — Defeito em tarefa `done`: o fluxo de hotfix

**Situação:** `T-LOGIN-SPEC` já está `done` (terminal e imutável) e o QA achou
uma lacuna. `done` **nunca** reabre. O caminho é: reportar a issue → o
Orchestrator cria um **hotfix** (nova tarefa) → executar o ciclo na nova tarefa.

```powershell
# 1) QA reporta o defeito apontando a tarefa done
esaa issue report T-LOGIN-SPEC --actor agent-qa `
  --issue-id ISS-LOGIN-DONE --severity high `
  --title "Spec aprovada deixou lacuna" `
  --symptom "Fluxo de erro nao foi documentado" `
  --repro-step "Comparar spec aprovada com o teste de QA" `
  --fixes T-LOGIN-SPEC

# 2) Orchestrator cria a tarefa de correção (escopo declarado)
esaa hotfix create --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --scope-patch src/hotfix/

# 3) Executa o ciclo na hotfix — complete exige issue_id, fixes e 2+ checks
esaa claim <HOTFIX-ID> --actor agent-impl
esaa complete <HOTFIX-ID> --actor agent-impl `
  --check "lacuna do fluxo de erro coberta" `
  --check "teste de regressao adicionado" `
  --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --file-updates updates.json
```

Detalhes que importam:

- `hotfix create` gera, no core atual, uma tarefa `impl`. `--scope-patch`
  (repetível) **restringe** ainda mais a escrita, mas não troca a boundary do
  `task_kind`. Para correção puramente documental, prefira criar uma nova tarefa
  `spec` com `--boundary-grant` quando necessário.
- A tarefa original permanece intacta. O hotfix é trabalho novo, rastreável até
  a issue.

**Atalho de demonstração:** para ver o protocolo ponta a ponta sem montar tudo
à mão, rode o trace pronto:

```powershell
esaa scenario hotfix                 # usa um workspace temporário
esaa scenario hotfix --current       # opera no workspace atual
esaa scenario hotfix --issue-id ISS-DEMO
```

---

## Cenário 10 — Rejeitar um output inválido

**Situação:** um agente enviou um envelope que viola um gate (ex.: colapsou
`claim`+`complete`). O Orchestrator registra a rejeição com código canônico — o
histórico guarda a tentativa inválida.

```powershell
esaa reject T-LOGIN-IMPL `
  --error-code ACTION_COLLAPSE `
  --source-action complete `
  --message "Envelope tentou claim e complete na mesma invocacao"
```

O `--error-code` vem da fonte única `src/esaa/reject_codes.py`
(`ACTION_COLLAPSE`, `MISSING_CLAIM`, `PRIOR_STATUS_MISMATCH`,
`LOCK_VIOLATION`, `MISSING_VERIFICATION`, ...). Para ver o vocabulário canônico
de actions e reject codes:

```powershell
esaa vocabulary
esaa vocabulary --profile public
```

---

## Cenário 11 — Usar um plugin de roadmap

**Situação:** você quer instalar um conjunto de tarefas pré-empacotado (ex.: um
roadmap de "security" ou de cliente SSO) em vez de criar tarefa a tarefa.
**Instalar não ativa** — a ativação é um passo explícito para não tornar tarefas
executáveis por acidente.

```powershell
# 1) Descobrir o que existe (bundled e catálogo externo em ~/.esaa/plugins)
esaa plugin list --available
esaa plugin list --available --external
esaa plugin list                      # o que já está instalado neste workspace

# 2) Validar e diagnosticar antes de instalar
esaa plugin validate security
esaa plugin doctor security           # checa diretório, manifest, roadmap, schema, paths

# 3) Instalar (registra em .roadmap/plugins.lock.json — NÃO ativa)
esaa plugin install security

# 4) Ativar uma execução do roadmap (aí sim as tarefas ficam elegíveis)
esaa roadmap activate security --execution-id default

# 5) Acompanhar
esaa roadmap status --detail
esaa eligible
```

As tarefas do plugin entram com ids **namespaceados** pela execução:

```text
security-default-T-001
```

Controlar a execução sem desinstalar o pacote:

```powershell
esaa roadmap list --detail
esaa roadmap pause security --execution-id default
esaa roadmap resume security --execution-id default
esaa roadmap deactivate security --execution-id default   # tira de novas elegibilidades
esaa plugin remove security                               # remove o estado de instalação
```

Visão planejado-vs-projetado por plugin (quanto do roadmap já saiu do papel):

```powershell
esaa plugin-status --detail
esaa plugin-status --plugin roadmap.sso-client.json   # filtra um arquivo de roadmap
```

> Se você não fornecer input na ativação, o ESAA copia o exemplo do plugin para
> `.roadmap/plugin-inputs/` e o valida contra o schema de input do plugin. Para
> fornecer o seu: `esaa roadmap activate security --input meu-input.json`.

---

## Cenário 12 — Criar e publicar o seu próprio plugin

**Situação:** você quer empacotar um roadmap reutilizável. Um plugin ESAA é um
**diretório** (não um arquivo compactado) com `plugin.json` na raiz.

```powershell
# 1) Scaffold de um pacote inicial válido
esaa plugin new minha-feature
```

Isso gera a estrutura mínima:

```text
minha-feature/
  plugin.json                                   # identidade + entrypoints
  roadmap.template.json                         # tarefas planejadas (T-001 spec...)
  inputs/minha-feature.local.example.json       # exemplo de input local
  schemas/minha-feature-input.schema.json       # schema do input
  README.md
```

`plugin.json` declara a identidade e os entrypoints (versão de core compatível,
namespace de task ids, capabilities). O `roadmap.template.json` lista as tarefas
com ids locais simples (`T-001`); o ESAA os namespaceia na ativação
(`minha-feature-default-T-001`).

```powershell
# 2) Editar roadmap.template.json com as suas tarefas, depois validar
esaa plugin validate ./minha-feature
esaa plugin doctor ./minha-feature      # diagnóstico check a check

# 3) Instalar a partir do diretório local e ativar
esaa plugin install ./minha-feature
esaa roadmap activate minha-feature --execution-id default
```

Para distribuir via catálogo externo, coloque o diretório do plugin em
`~/.esaa/plugins/` (ou aponte `ESAA_PLUGINS_HOME`); ele passa a aparecer em
`esaa plugin list --available --external`. Veja os guias dedicados em
[docs/plugins/](../plugins/authoring.md) (authoring, installing, lifecycle,
security).

---

## Cenário 13 — Registrar as capacidades de um runner

**Situação:** o seu runner LLM tem um conjunto específico de ferramentas/shells
disponíveis. Você quer que o `dispatch-context` informe isso ao agente, sem
poluir o contrato canônico.

```powershell
# 1) Validar o YAML de capacidades antes de registrar
esaa input commands validate runner-claude-code.yaml

# 2) Registrar para um runner (grava em .roadmap/runner-inputs/commands/<id>.yaml)
esaa input commands register runner-claude-code.yaml --runner-id claude-code

# 3) Conferir o que está registrado
esaa input commands show --runner-id claude-code
```

Esse input é **local ao workspace**, não canônico. A partir do registro, ele é
injetado no `dispatch-context` como `runtime_capabilities` (Cenário 3) — o
agente passa a saber quais superfícies de shell/ferramentas pode usar.

---

## Cenário 14 — Telemetria de runner externo

**Situação:** um runner LLM externo terminou uma tarefa e você quer registrar
latência, tokens e custo como evidência auditável. Isso é reservado ao
**Orchestrator/operador** — agentes não emitem `runner.metrics`.

```powershell
# Via flags
esaa runner metrics `
  --task-id T-LOGIN-IMPL --actor agent-impl `
  --runner-id claude-code --runner-kind llm `
  --model claude-opus-4-8 --command-surface cli `
  --latency-ms 4200 --input-tokens 1800 --output-tokens 950 `
  --cost-estimate 0.12 --status success

# Ou via JSON (mesmos campos)
esaa runner metrics --file metrics.json
```

Na prática informe ao menos `task_id`, `actor`, `runner_id`, `runner_kind`,
`command_surface` e `status` (∈ `success`/`failed`/`cancelled`/`unknown`).
Registra um evento `runner.metrics`. Para uma visão estruturada do runtime do
workspace inteiro:

```powershell
esaa metrics
```

---

## Cenário 15 — Auditoria e integridade

**Situação:** você suspeita de drift (alguém editou uma projeção à mão) ou
precisa reconstruir o estado em um ponto do histórico para auditar.

```powershell
# Reprojetar e comparar hash -> ok | mismatch | corrupted
esaa verify

# Também validar a hash chain do event store
esaa verify --chain

# Ancorar a hash chain (uma vez; --force só para recriar a âncora explicitamente)
esaa chain init

# Forçar a reprojeção dos read models a partir do event store
esaa project

# Reconstruir o estado até um evento (por seq numérico ou event_id)
esaa replay --until 42
esaa replay --until 42 --no-write     # calcula sem gravar as views (auditoria)
```

`verify` é a defesa contra drift: qualquer edição manual nas projeções ou no
event store é detectada por hash, e o CLI sai com código 2 em
`mismatch`/`corrupted`. `replay --no-write` é seguro para investigar "como o
estado estava no evento N" sem alterar nada.

---

## Cenário 16 — Manutenção do event store

**Situação:** o `activity.jsonl` cresceu muito, ou ficou um efeito de arquivo
pendente após um crash, ou há arquivos esperando num inbox para serem
processados.

```powershell
# Checkpoint cobrindo eventos com event_seq <= N (mantém replay auditável)
esaa snapshot --before 100
esaa snapshot --before 100 --compact      # também arquiva os eventos incluídos
esaa snapshot --before 100 --compact --dry-run   # mostra o plano sem escrever

# Processar arquivos pendentes do inbox governado por arquivo
esaa process --dry-run
esaa process

# Recuperar efeitos de arquivo ausentes a partir dos artifacts forenses
esaa effects recover --dry-run
esaa effects recover

# Reiniciar o event store (destrutivo: faz backup e trunca)
esaa activity clear --dry-run             # inspeciona o plano
esaa activity clear --force               # backup em .roadmap/backups/ e limpa
esaa activity clear --force --backup-dir .roadmap/backups
```

Cuidados:

- `activity clear --force` é destrutivo. Rode `verify` antes e depois, e
  garanta um único runner ativo no workspace.
- `effects recover` reaplica efeitos a partir de
  `.roadmap/artifacts/file-effects/` — é a recuperação pós-crash do commit
  atômico. `--dry-run` lista o que seria reaplicado.
- `snapshot --compact` evita o event store crescer indefinidamente sem perder a
  capacidade de replay.

---

## Cenário 17 — Concorrência e identidade de runner

**Situação:** dois runners poderiam tocar o mesmo workspace. Até locks robustos
estarem validados, a regra é **um runner por vez** por workspace.

```powershell
# Forma explícita por comando (precedência: --runner > ESAA_RUNNER_ID > default)
esaa --runner claude-code submit output.json --actor agent-spec

# Forma por sessão
$env:ESAA_RUNNER_ID = "codex"
esaa task create T-X --kind spec --title "..."
```

Disciplina operacional:

- Use `--runner <id>` ou `ESAA_RUNNER_ID` em `submit`, `task create`, `init`,
  `run` e demais escritas. O agente **nunca** envia o campo `runner`; o
  Orchestrator carimba.
- Se `.roadmap/activity.jsonl.lock` existir antes de você escrever, **pare e
  pergunte**.
- Se encontrar `STORE_LOCK_TIMEOUT`, `JSONL_INVALID` ou `EVENT_SEQ_*`, pare e
  reporte.
- Após qualquer escrita governada, rode `esaa verify`.
- O estado é **por workspace**: cada pasta com `.roadmap/` é um universo
  independente. `--root <path>` escolhe qual.

---

## Cenário 18 — Operar runners reais: Claude Code, Codex, Gemini CLI, Grok

**Situação:** você quer conduzir o ciclo do ESAA usando um agente de linha de
comando — Claude Code, Codex (OpenAI), Gemini CLI (Google) ou Grok (xAI). A boa
notícia: **o ESAA é agnóstico ao modelo e à ferramenta**. Não há MCP, plugin de
provedor nem SDK. Para o ESAA, um "runner" é apenas duas coisas:

1. um **carimbo de proveniência** (`--runner <id>`, G08) gravado em cada evento;
2. um processo que produz o **envelope `agent.result`** em JSON puro e o submete
   via `esaa submit`.

Qualquer CLI de LLM que saiba ler um prompt e devolver JSON serve. O que muda de
ferramenta para ferramenta é só **onde você coloca o contrato do agente** (o
arquivo de instruções que cada CLI lê) e **o `runner_id`** que você carimba.

### O laço universal (idêntico para os quatro)

```powershell
# 1) Escolher trabalho e montar o contexto do agente
esaa --runner <id> eligible
esaa --runner <id> dispatch-context T-X      # cole isto no prompt do agente

# 2) O agente responde SÓ o envelope JSON -> salve em envelope.json
#    { "activity_event": {...}, "file_updates": [...] }

# 3) Validar e aplicar pelo gate
esaa --runner <id> submit envelope.json --actor agent-<kind> --dry-run
esaa --runner <id> submit envelope.json --actor agent-<kind>

# 4) Conferir integridade ao fim de cada onda
esaa --runner <id> verify
```

Passos puramente determinísticos (claim, review de rotina) podem usar os comandos
diretos e **não gastam tokens**: `esaa --runner <id> claim T-X --actor agent-spec`.

### Matriz por ferramenta

| Ferramenta | `--runner <id>` | Registrado por padrão? | `runner_kind` | Onde colocar o contrato do agente |
|---|---|---|---|---|
| **Claude Code** | `claude-code` | ✅ sim | `llm-agent` | `CLAUDE.md` (ou `.claude/CLAUDE.md`) |
| **Codex** (OpenAI) | `codex` | ✅ sim | `llm-agent` | `AGENTS.md` |
| **Gemini CLI** (Google) | `gemini-cli` | ❌ registrar | `llm-agent` | `GEMINI.md` (e/ou `AGENTS.md`) |
| **Grok Build** (xAI) | `grok` | ❌ registrar | `llm-agent` | `AGENTS.md` (também auto-lê `CLAUDE.md` e `.claude/`) |

Este repositório já traz `.claude/CLAUDE.md` e `AGENTS.md` — ambos refletem o
`AGENT_CONTRACT.yaml`. **Grok Build** ([x.ai/cli](https://x.ai/cli)) reconhece os
dois nativamente (lê a família `AGENTS.md` e auto-lê `CLAUDE.md` + `.claude/`),
então pega o contrato sem configuração extra. Para o **Gemini CLI**, aponte a
ferramenta para esse mesmo contrato (um `GEMINI.md` que repita as regras, ou o
caminho de instruções que a CLI aceitar). A regra de ouro do contrato é sempre a
mesma: **uma action por invocação, `prior_status` sempre, `file_updates` só com
`complete`, JSON puro, na dúvida `issue.report`**.

### "Registrado por padrão?" — permissive vs strict

O comportamento depende de `runner_validation` em `.roadmap/RUNTIME_POLICY.yaml`:

- **`permissive`** (default deste workspace): **qualquer** `runner_id` é aceito e
  carimbado. `gemini-cli` e `grok` funcionam imediatamente, sem registro.
- **`strict`**: no caminho `submit`, um `runner_id` fora da seção `runners:` de
  `.roadmap/agents_swarm.yaml` é rejeitado com `RUNNER_UNKNOWN` **antes** dos
  workflow gates. (Comandos administrativos do operador — `task create`, `init`,
  `verify` — não exigem registro.)

Para habilitar Gemini/Grok sob strict, **o operador** adiciona-os ao registro
(editar config em `.roadmap/` é ação de operador, registrada nas notes):

```yaml
# .roadmap/agents_swarm.yaml  (seção runners:)
runners:
  claude-code:   { display_name: "Claude Code (CLI)", kind: "llm-agent" }
  codex:         { display_name: "Codex",              kind: "llm-agent" }
  gemini-cli:    { display_name: "Gemini CLI (Google)", kind: "llm-agent" }
  grok:          { display_name: "Grok (xAI)",          kind: "llm-agent" }
```

### Exemplo ponta a ponta com Gemini CLI

```powershell
$env:ESAA_RUNNER_ID = "gemini-cli"     # carimbo de proveniência

# 1) contexto
esaa eligible
esaa dispatch-context T-LOGIN-SPEC > ctx.json

# 2) rodar o agente apontando para o contrato (GEMINI.md) e o contexto
#    -> a CLI deve responder APENAS o envelope JSON; salve em envelope.json

# 3) aplicar e registrar telemetria
esaa submit envelope.json --actor agent-spec --dry-run
esaa submit envelope.json --actor agent-spec
esaa runner metrics --task-id T-LOGIN-SPEC --actor agent-spec `
  --runner-id gemini-cli --runner-kind llm-agent `
  --command-surface cli --status success
esaa verify
```

Troque `gemini-cli` por `grok`, `codex` ou `claude-code` e **nada mais muda** no
laço — só o carimbo e o arquivo de instruções que aquela CLI lê.

> O guia [Operando Codex e Claude Code como runners](esaa-runners-codex-claude-code.md)
> detalha o envelope, os 5 gates e as receitas de despacho — vale para qualquer
> uma das quatro ferramentas.

---

## Cenário 19 — Tarefas com runners diferentes (workflow heterogêneo)

**Situação:** você quer usar o melhor de cada ferramenta no mesmo workspace — por
exemplo, a spec pelo Gemini CLI, a implementação pelo Codex e o review pelo
Claude Code. Isso é **suportado e auditável**, porque no ESAA o runner é um
**carimbo por evento**, e a trava de tarefa (WG-004) é por **`actor`**
(identidade do agente), **não** pelo runner — o runner nunca é comparado entre
`claim` e `complete` (`state_machine.py`, `_ensure_owner`).

### A) Heterogêneo por tarefa (hand-off sequencial) — o padrão real

Esse é o fluxo mais comum: **um runner é dono da tarefa do início ao fim**. Um
runner ativo por vez; cada tarefa com seu veículo (a exceção legítima é a
*continuação por exaustão de tokens* — variação B):

```powershell
# spec executada pelo Gemini CLI
esaa --runner gemini-cli claim    T-LOGIN-SPEC --actor agent-spec
esaa --runner gemini-cli complete T-LOGIN-SPEC --actor agent-spec `
  --check "spec cobre os 3 fluxos" --file-updates spec.json
esaa --runner gemini-cli verify

# impl executada pelo Codex
esaa --runner codex claim    T-LOGIN-IMPL --actor agent-impl
esaa --runner codex complete T-LOGIN-IMPL --actor agent-impl `
  --check "impl segue a spec" --check "testes passam" --file-updates impl.json
esaa --runner codex verify

# review executada pelo Claude Code (role QA)
esaa --runner claude-code review T-LOGIN-IMPL --actor agent-qa --decision approve
esaa --runner claude-code verify
```

Cada evento em `.roadmap/activity.jsonl` carrega seu próprio
`runner.runner_id` → auditoria completa de **qual veículo** fez **qual
transição**. Cruze com a telemetria por runner:

```powershell
esaa --runner codex runner metrics --task-id T-LOGIN-IMPL --actor agent-impl `
  --runner-id codex --runner-kind llm-agent --command-surface cli --status success
esaa metrics
```

**Runner constante, actor muda no review.** No uso real (e no histórico deste
workspace), o `runner` permanece o mesmo do `claim` ao `done` — o que muda é o
**actor** no gate de review. Sob a policy `review_authorization: qa_role`
(default deste workspace), quem completou **não** pode auto-aprovar a menos que
já tenha role QA: para chegar a `done`, o `review` precisa de um actor de role
`qa` (ou `orchestrator`). Logo, o caminho típico de uma tarefa é:

```text
claim/complete  -> agent-spec | agent-impl | agent-hotfix   (runner X)
review/approve  -> agent-qa                                 (runner X)
```

O runner não troca; o actor sim, apenas na fronteira do review. Se você quer
manter **o actor também constante** do início ao fim, conduza a tarefa inteira
com um actor de role QA/orchestrator (ex.: `agent-qa` faz claim, complete e
review) — aí `done` é alcançado sem trocar de identidade.

> **Dica de proveniência:** defina `ESAA_RUNNER_ID` por sessão. Se você passar
> `--runner` só no `claim` e esquecer no `complete`, o carimbo cai para
> `unattended` (default) e a tarefa fica com runner inconsistente no histórico —
> um drift acidental, não um hand-off.

### B) Continuação por exaustão de tokens (hand-off real)

Acontece de verdade: o runner que reivindicou a tarefa fica sem tokens/contexto
no meio do trabalho e você pede a **outro** runner que continue de onde o
anterior parou. O ESAA suporta isso porque a trava é por **`actor`**, não pelo
runner — o runner que continua só precisa **reusar o mesmo `--actor`** do claim:

```powershell
# Runner 1 (Codex) reivindica e começa
esaa --runner codex claim T-X --actor agent-impl
# ... os tokens acabam no meio ...

# Runner 2 (Claude Code) conclui — MESMO actor, o gate aceita (assigned_to == actor)
esaa --runner claude-code complete T-X --actor agent-impl `
  --check "..." --file-updates updates.json
```

O que fica no histórico depende de **qual `--runner` você carimba na
continuação** (o bloco `runner` é resolvido de `ESAA_RUNNER_ID` no momento de
cada invocação, `events.py` → `resolve_runner`):

- **Proveniência honesta (recomendado):** carimbe `--runner <runner-que-continua>`
  nos eventos que ele de fato executa. O `activity.jsonl` passa a mostrar `claim`
  por `codex` e `complete` por `claude-code` — a auditoria reflete o hand-off
  real. Opcionalmente, `ESAA_ON_BEHALF_OF` registra a continuidade (ex.:
  claude-code atuando na sequência de codex); esse campo já viaja no bloco
  `runner` de todo evento.
- **Herdar o id anterior (o que costuma acontecer):** se você mantém o
  `ESAA_RUNNER_ID` do runner anterior, o trabalho do segundo runner é gravado
  **sob o nome do primeiro**. Funciona — o gate não checa continuidade de runner
  —, mas a proveniência atribui ao runner 1 algo que o runner 2 fez. É um detalhe
  de auditoria, não um erro de protocolo.

> A etiqueta "não reivindique tarefa atribuída a outro runner" (AGENTS.md §3)
> mira **sessões concorrentes** disputando a mesma tarefa — não esse hand-off
> sequencial e deliberado, em que só um runner está ativo por vez.

### C) Paralelo real (concorrente) — desenho permite, prática atual serializa

`esaa eligible` devolve `parallel_groups` — tarefas com boundaries de escrita
disjuntas, logicamente despacháveis a runners diferentes ao mesmo tempo:

```powershell
esaa eligible
# parallel_groups: [["T-A","T-B"]]  -> sem conflito de escrita
```

Duas ressalvas de honestidade operacional:

- A regra de concorrência vigente (CLAUDE.md / AGENTS.md §3) é **um runner por
  workspace até os locks robustos estarem validados**. Hoje você paraleliza a
  *decisão* (os grupos dizem o que é seguro), mas **serializa as escritas**.
- `esaa run --parallel N` despacha N tarefas em **um único** processo
  orchestrator → todos os eventos saem com **o mesmo** carimbo de runner
  (`make_event` resolve um `ESAA_RUNNER_ID` por processo). Não é um leque
  multi-runner. Multi-runner concorrente de verdade exige **sessões separadas**,
  cada uma com seu `--runner` — o que a regra atual desaconselha rodar ao mesmo
  tempo.

> **Resumo:** runners diferentes em tarefas diferentes → sim, à vontade
> (sequencial). Trocar de runner **no meio de uma tarefa** (continuação por
> exaustão) → sim, reusando o mesmo `--actor`; só cuide do carimbo de runner.
> Runners diferentes escrevendo **ao mesmo tempo** no mesmo workspace → ainda
> não, até os locks robustos fecharem. A barreira é de concorrência de escrita,
> não do modelo de proveniência — e **não** de integridade: veja por que o store
> não corrompe no
> [Cenário 20](#cenário-20--por-que-o-event-store-não-corrompe-sob-concorrência).

---

## Cenário 20 — Por que o event store não corrompe sob concorrência

**Situação:** você está avaliando o ESAA com olhar crítico e quer saber se a
regra "um runner por vez" (Cenário 17/19) esconde uma fragilidade. O que de fato
acontece se dois processos tentarem escrever no mesmo `.roadmap/activity.jsonl`?
A resposta curta: **a integridade é garantida por construção; a regra é política
conservadora, não um remendo sobre algo quebrado.** Abaixo, o mecanismo real,
com os pontos do código.

### 1. O log é sequencial por construção

Toda escrita governada apenas **anexa** eventos ao log append-only — única fonte
da verdade. Duas propriedades o tornam intrinsecamente serial:

- **`event_seq` estritamente monotônico**: o próximo é sempre `último + 1`
  (`store.py` → `next_event_seq`). Não existem dois eventos com o mesmo seq.
- **hash chain**: cada evento carrega `prev_event_hash = event_hash do anterior`
  (encadeado em `store.py` → `_prepare_events_for_append`, validado por
  `_validate_hash_chain`). A cadeia só fecha se os eventos forem encadeados
  **em ordem** — qualquer reordenação ou edição posterior quebra a verificação.

### 2. Escritas são serializadas por um lock transacional

O caminho de escrita (`append_transactional`, FIX-1806) executa **todo** o ciclo
sob um lock exclusivo de SO:

```text
adquire lock → parse → valida staleness → decide seq → materialize (valida)
            → append → read-after-write → salva projeções → libera lock
```

O lock nasce de `os.open(..., O_CREAT | O_EXCL)` — criação atômica de
`.roadmap/activity.jsonl.lock`, com metadados (`pid`, `hostname`, `runner_id`,
`acquired_at`). Quando o **runner B** chega e o **runner A** está com o lock, B
**espera e tenta de novo** (retry de 50 ms); se A não liberar dentro do timeout
(30 s no caminho transacional), B recebe **`STORE_LOCK_TIMEOUT`** e para. As
linhas dos dois **nunca se intercalam** no arquivo.

### 3. As quatro camadas de defesa

| Camada | O que protege | Sinal / código |
|---|---|---|
| **Lock exclusivo** (`O_EXCL`) | dois processos no caminho de escrita ao mesmo tempo | `STORE_LOCK_TIMEOUT` |
| **Optimistic concurrency** | append calculado sobre estado já desatualizado | `STALE_STATE_SEQ` / `STALE_STATE_HASH` |
| **Read-after-write** | o que foi gravado é o que se queria gravar | `APPEND_VERIFY_FAILED` |
| **Hash chain** | qualquer quebra/edição posterior do log | `EVENT_SEQ_*`, `verify --chain` |

A peça-chave para o crítico é o **`STALE_STATE_SEQ`**: mesmo que B adquira o lock
logo após A, se o estado mudou desde que B montou seu envelope, o append é
**rejeitado** em vez de aplicado sobre base velha. Isso fecha a janela TOCTOU
(o intervalo entre "ler estado" e "escrever") — a serialização é *correta*, não
apenas *mutuamente exclusiva*.

### 4. O que isso garante — e o que não promete

**Garante:** nunca há interleaving de escrita; nunca há append sobre estado
obsoleto; toda gravação é reverificada por leitura; a cadeia detecta adulteração
a posteriori. Em disco local, o event store **não corrompe** sob tentativa de
escrita concorrente.

**Não promete:** (a) *throughput* paralelo — as escritas serializam, então dois
runners concorrentes não ganham velocidade, só contenção; (b) atomicidade do
`O_EXCL` em **filesystems de rede** (NFS/SMB), onde a semântica de criação
exclusiva e a detecção de lock obsoleto (takeover por TTL/pid vivo) têm casos de
borda; (c) coordenação **entre hosts** além da expiração por TTL.

### 5. Por que então "um runner por vez"?

É política conservadora pelos três motivos acima — **não** porque o store seja
frágil em disco local. Os contratos pedem validação **no workspace alvo**
(CLAUDE.md / AGENTS.md §3) justamente porque a garantia depende do filesystem
onde o `.roadmap/` mora. Em disco local a serialização é sólida; em rede,
aguarde a validação antes de habilitar multi-runner concorrente.

### 6. Como auditar você mesmo

```powershell
esaa verify --chain                 # valida event_seq monotônico + hash chain
esaa replay --until 50 --no-write   # reconstrói o estado no evento 50 sem gravar
# inspecionar o lock vivo (pid/hostname/runner_id/acquired_at):
Get-Content .roadmap/activity.jsonl.lock
```

> **Para o leitor crítico:** "dois runners escrevendo ao mesmo tempo" no ESAA é,
> na prática, "um escreve, o outro espera ou recebe `STORE_LOCK_TIMEOUT`". A
> ausência de multi-runner concorrente é uma decisão de cautela operacional
> (sem ganho de throughput + dependência de filesystem), e não uma brecha de
> integridade do event store.

---

## Referência rápida comando → cenário

| Comando | Para quê | Cenário |
|---|---|---|
| `bootstrap` | instalar templates de governança | 1 |
| `init` | estado canônico limpo | 1 |
| `verify` / `verify --chain` | checar consistência / hash chain | 1, 15 |
| `task create` | criar tarefa (Orchestrator) | 2 |
| `eligible` | o que pode rodar agora | 3 |
| `state` | status + próxima action | 3 |
| `dispatch-context` | pacote mínimo para o agente | 3, 13 |
| `claim` | reivindicar (todo→in_progress) | 4 |
| `complete` | concluir com evidência + arquivos | 4, 5 |
| `review` | aprovar/devolver (só QA) | 4 |
| `submit` | aplicar envelope agent.result | 6 |
| `run` | orquestração automática | 7 |
| `issue report` | bloqueio fail-closed | 8 |
| `issue resolve` | encerrar issue | 8 |
| `hotfix create` | correção de tarefa done | 9 |
| `scenario hotfix` | trace demonstrável ponta a ponta | 9 |
| `reject` | registrar output inválido | 10 |
| `vocabulary` | actions e reject codes canônicos | 10 |
| `plugin list/validate/doctor/install/remove` | ciclo de vida do pacote | 11, 12 |
| `plugin new` | scaffold de plugin | 12 |
| `roadmap activate/status/pause/resume/deactivate/list` | execução de roadmap | 11 |
| `plugin-status` | planejado vs projetado | 11 |
| `input commands validate/register/show` | capacidades do runner | 13 |
| `runner metrics` | telemetria de runner externo | 14 |
| `metrics` | métricas do runtime | 14 |
| `chain init` | ancorar hash chain | 15 |
| `project` | reprojetar read models | 15 |
| `replay` | reconstruir estado num ponto | 15 |
| `snapshot` | checkpoint/compactação | 16 |
| `process` | inbox governado por arquivo | 16 |
| `effects recover` | recuperar file effects | 16 |
| `activity clear` | reiniciar event store | 16 |

## Mapa de troubleshooting

| Você vê | Significa | O que fazer |
|---|---|---|
| `RUNNER_UNKNOWN` | runner fora do registro em policy strict | use um runner conhecido em `--runner`/`ESAA_RUNNER_ID` (Cenário 1) |
| `MISSING_CLAIM` | `complete`/`review` sem `claim` prévio | rode `claim` primeiro (Cenário 4) |
| `LOCK_VIOLATION` | quem completa ≠ quem reivindicou | complete com o mesmo `--actor` do claim |
| `PRIOR_STATUS_MISMATCH` | `prior_status` não bate com o real | rode `esaa state <id>` e corrija; não consome attempt |
| `ACTION_COLLAPSE` | mais de uma action no envelope | uma action por invocação (Cenário 6) |
| `MISSING_VERIFICATION` | `complete` sem `--check` | adicione checks (1 spec/impl/qa, 2 hotfix) |
| `EDIT_BASE_MISMATCH` | arquivo mudou desde o `base_sha256` | releia o arquivo e refaça o hash (Cenário 5) |
| `EDIT_AMBIGUOUS` | `old_string` casa em vários trechos | use `replace_all=true` ou um trecho mais específico |
| `verify_status: mismatch`/`corrupted` | drift na projeção/event store | `esaa project`, investigue com `replay --no-write`, restaure backup |
| `STORE_LOCK_TIMEOUT` / `*.lock` presente | outro runner no workspace | pare e pergunte; um runner por vez (Cenário 17, 20) |
| `STALE_STATE_SEQ` / `STALE_STATE_HASH` | estado mudou desde que o envelope foi montado | recomponha sobre o estado atual e reenvie (Cenário 20) |
| `APPEND_VERIFY_FAILED` | read-after-write não conferiu o que foi gravado | rode `verify --chain`; investigue I/O/filesystem (Cenário 20) |

## Veja também

- [Referência completa do CLI](esaa-cli-reference.md) — sintaxe de cada flag
- [Primeiros passos](esaa-getting-started.md) — caminho mais curto
- [Operando Codex e Claude Code como runners](esaa-runners-codex-claude-code.md)
- [Por que usar o ESAA](esaa-why.md)
- Plugins: [authoring](../plugins/authoring.md) · [installing](../plugins/installing.md) · [lifecycle](../plugins/lifecycle.md) · [security](../plugins/security.md)
