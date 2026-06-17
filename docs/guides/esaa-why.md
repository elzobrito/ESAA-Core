# Por que usar o ESAA

🌐 **Português** · [English](esaa-why.en.md)

> **ESAA — Event Sourcing for Autonomous Agents.** Arquitetura de governança e
> protocolo event-sourced para agentes autônomos (Codex, Claude Code, scripts,
> humanos) trabalharem no mesmo projeto sem estado "mágico", sem histórico
> invisível e sem um agente atropelar o outro.

## O problema

Agentes de código (LLMs) são bons em produzir artefatos e ruins em disciplina
operacional. Sem governança, um fluxo multi-agente típico sofre de:

- **Estado mágico** — arquivos mudam sem registro de quem mudou, quando e por quê.
- **Histórico invisível** — decisões tomadas no meio de um prompt se perdem.
- **Colapso de etapas** — o agente "adianta" o trabalho: reivindica, executa e
  aprova tudo numa única resposta, sem ponto de controle.
- **Drift de estado** — o arquivo de status diz uma coisa, o repositório diz outra.
- **Retrabalho invisível** — o mesmo erro é repetido porque nada registra a lição.

## A solução em uma frase

> Todo avanço de estado é um **evento imutável** validado por um **único
> escritor** (o Orchestrator); agentes apenas **emitem intenções**, e qualquer
> estado legível é uma **projeção determinística** do event store — verificável
> por replay e hash.

## Recursos e problemas que resolvem

### Estado e auditoria

- **Event store**: registra tudo em `.roadmap/activity.jsonl`, com
  `event_seq` monotônico. Resolve histórico invisível, decisões perdidas e
  estado "mágico".
- **Read models**: projetam `roadmap.json`, `issues.json` e `lessons.json` para
  leitura rápida sem editar a fonte da verdade.
- **`verify` / `replay`**: recalculam projeções a partir do event store. Pegam
  drift, corrupção, edição manual e inconsistência entre log e projeção.
- **Snapshots/compaction (`snapshot`)**: criam checkpoints auditáveis para que o
  event store possa crescer sem perder capacidade de replay.

### Workflow governado

- **Orchestrator**: valida e aplica transições como único escritor. Impede que o
  agente escreva estado direto ou quebre protocolo.
- **State machine**: controla `todo → in_progress → review → done`. Evita pular
  etapas, concluir sem claim ou reabrir tarefa `done`.
- **Workflow gates (WG-001..005)**: bloqueiam outputs inválidos antes de
  persistir, como claim+complete colapsado, status errado, falta de verificação
  ou lock violado.
- **Boundaries**: limitam escrita por `task_kind` (`spec`, `impl`, `qa`). Evitam
  tarefa de documentação alterando código ou QA mexendo em `src/**`.
- **`file_updates` governado**: aplica arquivos só via `complete`, com staging
  atômico. Remove mutação solta sem evento, evidência ou validação.
- **`file_updates.edits`**: envia patches pequenos com `base_sha256`. Reduz
  payload e evita sobrescrever arquivo desatualizado.

### Despacho e runners

- **`eligible`**: calcula próximas tarefas executáveis e grupos paralelos. Evita
  escolher tarefa bloqueada, dependente ou fora do paralelismo seguro.
- **`state`**: mostra o status determinístico de uma tarefa e a próxima action
  esperada. O agente não precisa adivinhar se deve emitir claim ou complete.
- **`dispatch-context`**: entrega contexto mínimo por tarefa, incluindo status,
  action esperada, schema slice, lessons e capacidades de runtime.
- **Runtime capabilities (`input commands`)**: registra por runner as superfícies
  e ferramentas disponíveis. Resolve o problema "posso usar PowerShell, WSL,
  grep ou sed neste workspace?".
- **Runner provenance (`--runner`)**: carimba a identidade do runner em todo
  evento. Dá auditoria de quem executou cada transição.
- **Runner metrics (`runner metrics`)**: registra tokens, latência, modelo,
  status e superfície de comando. Dá telemetria real sem depender do provedor.

### Exceções, recuperação e extensão

- **`reject`**: registra `output.rejected` com código canônico. Erro de
  protocolo deixa trilha, em vez de virar conversa solta.
- **Issues**: registram bloqueios e falhas com `symptom` + `repro_steps`.
- **Lessons**: injetam aprendizados como constraints ativas em toda invocação.
- **Hotfix workflow**: defeito em tarefa `done` vira `issue.report` + hotfix ou
  nova tarefa corretiva; a tarefa original permanece imutável.
- **`process` (inbox)**: processa arquivos pendentes de `.roadmap/inbox/` como
  canal governado por arquivo.
- **`scenario`**: executa cenários determinísticos, como trace de hotfix, para
  validar o protocolo ponta a ponta.
- **`vocabulary`**: exibe mapeamentos canônicos de actions, reject codes e
  perfis, evitando cada runner inventar sua própria linguagem.
- **Plugins e roadmaps externos**: `plugin`, `plugin-status` e `roadmap`
  instalam, validam e ativam pacotes de tarefas sem misturar domínio no core.
- **Bootstrap e pacote PyPI**: `bootstrap` cria workspaces padronizados;
  `pip install esaa-core` disponibiliza `esaa` / `python -m esaa` fora do
  checkout local.
- **CLI no-token**: `claim`, `complete`, `review`, `task create` e comandos
  determinísticos evitam gastar chamada de LLM em transições mecânicas.

## Princípios de segurança operacional

- **Fail-closed**: na dúvida, o agente emite `issue.report` — nunca improvisa.
- **Locks e tentativas**: máximo de 3 tentativas por tarefa, cooldown de 2 min,
  TTL de 30 min por attempt (`RUNTIME_POLICY.yaml`).
- **`done` é imutável**: defeito em tarefa concluída gera hotfix, nunca reabertura.
- **Rejeições explícitas**: todo output inválido vira `output.rejected` com
  código canônico (fonte única: `src/esaa/reject_codes.py`).
- **Sem MCP**: a integração é por CLI local e arquivos — auditável e determinística.

## Leia em seguida

- [Guia de primeiros passos](esaa-getting-started.md)
- [Referência do CLI](esaa-cli-reference.md)
- [Operando Codex e Claude Code como runners](esaa-runners-codex-claude-code.md)
