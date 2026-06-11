# Threat Model - Identidade ESAA

> Escopo: G03 / SEC-02
> Objetivo: definir o que o ESAA assume como confiavel e quais ataques o modelo de actor/runner deve bloquear.

## Ativos protegidos

- Integridade do event store `.roadmap/activity.jsonl`.
- Estado derivado das tarefas (`roadmap.json`, `issues.json`, `lessons.json`).
- Boundaries de escrita por `task_kind`.
- Autoridade de review e transicao para `done`.
- File effects aplicados pelo Orchestrator.

## Fronteiras de confianca

Confiavel:

- Orchestrator/CLI ESAA executando localmente.
- File lock do event store enquanto estiver integro.
- `agents_swarm.yaml` e `RUNTIME_POLICY.yaml` versionados no workspace.
- Segredos de actor quando fornecidos por ambiente/keyfile fora do event store.

Nao confiavel por si so:

- String `actor` recebida em comando ou payload de automacao.
- Nome com prefixo `agent-qa*`.
- Conteudo do envelope produzido por agente.
- Input de plugin, inclusive roots externos e paths runtime.
- Resposta de adapter HTTP/LLM.

## Ameaças cobertas por G03

1. **Escalada por nome de actor:** um caller usa `agent-qa-fake` para obter role QA por prefixo. Mitigacao: strict actor registry, sem fallback por prefixo.
2. **Review nao autorizado:** actor que fez claim tenta aprovar a propria entrega sem role QA. Mitigacao: `review_authorization=qa_role` + role resolvida no swarm.
3. **Complete por terceiro:** actor diferente tenta completar task reivindicada. Mitigacao: WG-004 com `assigned_to` derivado do claim.
4. **Uso de actor registrado sem credencial:** caller conhece o nome `agent-qa` e tenta usa-lo. Mitigacao opcional: `identity.auth.mode=hmac` com `ACTOR_AUTH_FAILED`.
5. **Persistencia de segredo:** token aparece em event log ou projection. Mitigacao: token e entrada de comando apenas, nunca payload persistido.

## Ameaças fora de escopo imediato

- Usuario local com permissao de escrita direta em `.roadmap/activity.jsonl`; tratado por G02 hash chain e por controles de filesystem.
- Lock orfao/concorrencia no append; tratado por G04.
- Plugin apontando para diretorio arbitrario; tratado por G05.
- Comprometimento completo do host local; requer controles externos ao ESAA.

## Garantias resultantes

Com `identity.strict=true` e `review_authorization=qa_role`:

- Role e sempre autorizacao explicita do swarm.
- Prefixo de nome nao concede privilegio.
- Review approve so vem de QA/orchestrator autorizado.
- Complete ainda respeita ownership do claim.
- Falhas de identidade acontecem antes de schema/gates/efeitos, mantendo fail-closed.