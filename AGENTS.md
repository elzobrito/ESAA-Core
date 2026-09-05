# AGENTS.md — ESAA

O ESAA não usa MCP. Use `python -m esaa`, com `--root` apontando para este
workspace. O pacote Python é `esaa-core`; o módulo é `esaa`.

## Autoridade e contexto

O Orchestrator é o único escritor do event store e dos efeitos finais.
[AGENT_CONTRACT](.roadmap/AGENT_CONTRACT.yaml),
[ORCHESTRATOR_CONTRACT](.roadmap/ORCHESTRATOR_CONTRACT.yaml),
[schema do agente](.roadmap/agent_result.schema.json) e
[RUNTIME_POLICY](.roadmap/RUNTIME_POLICY.yaml) definem as regras aplicáveis.
Não edite diretamente `.roadmap/activity.jsonl` nem suas projeções
(`roadmap.json`, `issues.json`, `lessons.json`, `project_profile.json`).

Para trabalhar numa tarefa, obtenha `python -m esaa dispatch-context TASK-ID`.
Use `eligible` para descobrir tarefas disponíveis e `state TASK-ID` para estado.
Leia somente as referências necessárias à tarefa; padrões de leitura autorizada
não são uma exigência de varrer o repositório. O contexto contém referências a
artefatos; recupere seu conteúdo quando necessário dentro dos limites autorizados.
Os perfis PARCER em `.roadmap/` são orientação por papel, carregada sob demanda.

## Trabalho e conclusão

Consultas e diagnósticos são somente leitura: não emita transições nem
`file_updates`. Relate o resultado e as limitações relevantes.

Na execução governada, `claim` e `complete` são submissões separadas. Cada envelope
contém uma `activity_event` e `prior_status` coerente. JSON puro é obrigatório no
envelope submetido ao Orchestrator, não nas mensagens de conversa.
O actor que reivindicou completa; `file_updates` só acompanha `complete`.
A revisão segue o papel autorizado e a política ativa. `done` é terminal:
problemas exigem `issue.report` e o fluxo de hotfix, sem reabrir a tarefa original.

Investigue contexto recuperável e resolva escolhas locais reversíveis dentro do
escopo autorizado sem pedir aprovação a cada passo. Prepare e valide candidatos
em ambiente permitido; os efeitos finais continuam via `file_updates`.
Quando a tarefa incluir execução, inspeção e correção, prossiga até satisfazer os
critérios de aceitação e reúna verificações reais antes de `complete`.
Respeite os mínimos de checks do contrato; `complete` não é aprovação nem publicação.

Obtenha a decisão necessária antes de alterar requisitos, permissões ou efeitos
externos ainda não autorizados. Se um requisito material continuar indefinido,
uma dependência obrigatória faltar ou um boundary impedir a entrega, reporte
`issue.report` com evidências; não ultrapasse o limite nem invente autorização.
Lessons aplicáveis em `reject`, `require_field` ou `require_step` são obrigatórias.
Considere `warn` sem convertê-lo por si só em bloqueio ou impor texto fixo de aceite.

## Proveniência e integridade

Identifique o runner real em cada comando que escreve eventos:
`python -m esaa --runner codex submit --actor agent-impl result.json`.
Use o identificador do seu runner, não copie `codex` se executar por outro runner.
O Orchestrator carimba `runner`; não o inclua no JSON do agente. Registro e modo
strict são definidos em [agents_swarm](.roadmap/agents_swarm.yaml) e RUNTIME_POLICY.
Após escrita governada, execute `python -m esaa verify`.

No runtime que oferece locks com metadados, releitura sob lock e verificação da
escrita, deixe a CLI tratar a contenção; a existência transitória do lock não
exige intervenção manual. Isso não autoriza tarefas de outro responsável nem
edições concorrentes nos mesmos arquivos. Em runtimes sem essas garantias,
mantenha um runner por workspace e interrompa a escrita se houver lock.
Nunca remova locks manualmente. Interrompa a operação afetada e relate evidências
em `STORE_LOCK_TIMEOUT`, `JSONL_INVALID`, `EVENT_SEQ_*`, `APPEND_VERIFY_FAILED`
ou falha de integridade; não contorne o mecanismo.

Para sintaxe específica, use `python -m esaa <comando> --help` e o contrato local.

## Desenvolvimento do ESAA-Core

Use `PYTHONPATH=src python -B -m esaa` no checkout para não importar outro pacote
instalado. Consulte [CONTRIBUTING](CONTRIBUTING.md) ao contribuir,
[o guia de runners](docs/guides/esaa-runners-codex-claude-code.md) para submissões e
[a referência CLI](docs/guides/esaa-cli-reference.md) para operações específicas.
Templates em `src/esaa/` são distribuídos a novos workspaces; contratos ativos
em `.roadmap/` podem ter diferenças intencionais. Não os sincronize por cópia.
