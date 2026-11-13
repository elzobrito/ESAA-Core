# AGENTS.md — ESAA

O ESAA não usa MCP. Use `python -m esaa --root CAMINHO`; pacote `esaa-core`,
módulo `esaa`. O Orchestrator é o único escritor do event store e dos efeitos
finais. Nunca edite `.roadmap/activity.jsonl` nem suas projeções (`roadmap.json`,
`issues.json`, `lessons.json`, `project_profile.json`).

Use `eligible` e `state TASK-ID` para consultar; antes de trabalhar, obtenha
`dispatch-context TASK-ID`. Ele traz boundaries, schema, lessons, comando concreto
(`next_command` e `next_command_argv`) e `example_envelope`. Adapte os checks às
verificações reais. `example_stdin`, quando presente, é `[]`: substitua pelo array
com os artefatos preparados dentro dos outputs e boundaries, pois o exemplo vazio
não entrega arquivos. Leia as referências necessárias à tarefa, sem varrer todo o
repositório por causa de padrões de leitura autorizada.

Os contratos são autoridade; sua leitura integral e os perfis PARCER só são
necessários para diagnosticar uma submissão rejeitada:

- `SCHEMA_*`, `MISSING_VERIFICATION`, `BOUNDARY_*`: [AGENT_CONTRACT](.roadmap/AGENT_CONTRACT.yaml)
  e [schema do agente](.roadmap/agent_result.schema.json).
- `MISSING_CLAIM`, `MISSING_COMPLETE`, `ACTION_COLLAPSE`, `PRIOR_STATUS_MISMATCH`,
  `LOCK_VIOLATION`, `IMMUTABLE_DONE_VIOLATION`: [ORCHESTRATOR_CONTRACT](.roadmap/ORCHESTRATOR_CONTRACT.yaml).
- `REVIEW_*`, `RUNNER_*`, `OPERATOR_REQUIRED`, `ATTEMPT_*`: [RUNTIME_POLICY](.roadmap/RUNTIME_POLICY.yaml)
  e [agents_swarm](.roadmap/agents_swarm.yaml). Para rejeições de especialização,
  leia apenas `.roadmap/PARCER_PROFILE.<papel>.yaml` do papel correspondente.

Consultas e diagnósticos são somente leitura: não emita transições nem
`file_updates`. Na execução, siga `todo → claim → in_progress → complete → review
→ done`. `claim` e `complete` são submissões separadas, com uma `activity_event`
e `prior_status` coerente por envelope. JSON puro é obrigatório no envelope
submetido ao Orchestrator, não na conversa. O actor que reivindicou completa;
`file_updates` só acompanha `complete`. A revisão segue papel e política ativos;
`complete` não é aprovação nem publicação. `done` é terminal: problemas exigem
`issue.report` e hotfix, sem reabrir a tarefa original.

Investigue contexto recuperável e resolva escolhas locais reversíveis sem pedir
aprovação a cada passo. Prepare, inspecione e corrija candidatos em ambiente
permitido até cumprir os critérios de aceite; reúna verificações reais e os
mínimos de checks antes de `complete`. Efeitos finais passam por `file_updates`.
Obtenha decisão antes de alterar requisitos, permissões ou efeitos externos ainda
não autorizados. Requisito material indefinido, dependência obrigatória ausente ou
boundary impeditivo exigem `issue.report` com evidências, sem inventar autorização.
Lessons em `reject`, `require_field` ou `require_step` são obrigatórias; considere
`warn` sem transformá-lo por si só em bloqueio ou texto fixo de aceite.

Identifique o runner real em cada escrita: `python -m esaa --runner codex submit
--actor agent-impl result.json`. Troque `codex` pelo runner que executa; nunca o
inclua no JSON: o Orchestrator o carimba. Após escrita, execute `verify`.

Quando o runtime oferece metadados de lock, releitura sob lock e verificação da
escrita, deixe a CLI tratar contenção. Lock transitório não exige intervenção nem
autoriza tarefas alheias ou edições concorrentes dos mesmos arquivos. Sem essas
garantias, mantenha um runner por workspace e interrompa a escrita se houver lock.
Nunca remova locks manualmente. Pare a operação afetada e relate evidências em
`STORE_LOCK_TIMEOUT`, `JSONL_INVALID`, `EVENT_SEQ_*`, `APPEND_VERIFY_FAILED` ou
falha de integridade. Para sintaxe, use `python -m esaa COMANDO --help`.
