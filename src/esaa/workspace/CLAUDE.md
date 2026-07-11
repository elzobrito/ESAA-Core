# CLAUDE.md — Contrato operacional ESAA

> Recorte estável para runners. Em divergência, os artefatos canônicos em `.roadmap/` prevalecem.
> O ESAA não usa MCP. Use a CLI ESAA: `python -m esaa`.

## Autoridade

ESAA é o protocolo de governança. O Orchestrator é o single writer do event store.
Agentes emitem intenções válidas; não editam diretamente `.roadmap/activity.jsonl`
nem os read models.

Fontes canônicas:
- Event store: `.roadmap/activity.jsonl`
- Projeções: `.roadmap/roadmap.json`, `.roadmap/issues.json`, `.roadmap/lessons.json`
- Contratos: `.roadmap/AGENT_CONTRACT.yaml`, `.roadmap/ORCHESTRATOR_CONTRACT.yaml`,
  `.roadmap/agent_result.schema.json`, `.roadmap/RUNTIME_POLICY.yaml`

## CLI

```bash
python -m esaa --root . verify
python -m esaa --root . eligible
python -m esaa --root . dispatch-context T-000
```

Comandos que escrevem eventos devem identificar o runner:

```bash
python -m esaa --root . --runner claude-code submit output.json --actor agent-spec
```

## Regras para agentes

- Emita exatamente uma `activity_event` por output.
- Use JSON puro, sem markdown fora do envelope.
- Inclua `prior_status` em todo output e mantenha-o coerente com o contexto recebido.
- Quando `dispatch-context` incluir `project_profile`, trate-o como o perfil operacional do projeto.
- Use `file_updates` somente com `action=complete`.
- Não inclua campos gerados pelo Orchestrator, como `runner`, `actor`, `event_seq`, `ts` ou `assigned_to`.
- Nunca reabra nem modifique tarefa `done`; reporte `issue.report`.
- Na dúvida, falhe fechado com `issue.report` e evidência reproduzível.

## Ciclo

1. `todo` -> `claim`
2. `in_progress` atribuído ao seu actor -> `complete`
3. `review` -> somente QA autorizado emite `review`
4. `done` -> apenas `issue.report`

## Lessons baseline

- LES-0001: nunca colapsar `claim` + `complete`.
- LES-0002: `file_updates` sem `action=complete` é inválido.
- LES-0003: `prior_status` é obrigatório e coerente.
