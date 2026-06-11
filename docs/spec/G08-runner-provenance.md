# G08 — Especificação: Proveniência de Runner (opções A+C)

> Tarefa: T-004 (spec) · Targets: PROV-01, PROV-02
> Contexto: o event store registra o papel contratual (`actor`) mas não o
> principal que o exerce. Nos 43 primeiros eventos deste workspace,
> agent-spec/impl/qa foram todos exercidos pelo mesmo runner (Claude/Cowork)
> sem nenhum registro estrutural disso.

## Conceitos

- **actor** (existente): papel contratual. Continua governando boundaries,
  gates e WG-004. Inalterado.
- **runner** (novo): o principal/veículo que emitiu o comando — ex.:
  `claude-cowork`, `claude-code`, `codex`, `human-terminal`.
- **on_behalf_of** (novo): identidade a quem o runner serve (e-mail/login do
  usuário), quando conhecida.

## PROV-01 — Bloco `runner` por evento (opção A)

Todo evento persistido ganha campo opcional de topo `runner`:

```json
{
  "schema_version": "0.4.1",
  "event_id": "EV-00000044",
  "actor": "agent-impl",
  "runner": {
    "runner_id": "claude-cowork",
    "runner_kind": "llm-agent",
    "command_surface": "cli",
    "on_behalf_of": "elzobrito@gmail.com"
  },
  ...
}
```

Regras:

1. **Quem grava é o single writer.** `make_event()` resolve o bloco no
   momento da criação do evento. O agente NUNCA envia `runner` — o campo
   entra em `forbidden_fields` do AGENT_CONTRACT (defesa em profundidade;
   o schema com `additionalProperties:false` já rejeita).
2. **Resolução com precedência:** flag global `--runner` do CLI >
   variável `ESAA_RUNNER_ID` > default `"unattended"`. Campos auxiliares:
   `ESAA_RUNNER_KIND`, `ESAA_COMMAND_SURFACE` (default `cli`),
   `ESAA_ON_BEHALF_OF`; ausentes viram `null`.
3. **Campos:** `runner_id` (str obrigatório no bloco), `runner_kind`,
   `command_surface`, `on_behalf_of` (str|null). Alinhados ao vocabulário
   já existente de `runner.metrics` (FIX-1812).
4. **Compatibilidade:** eventos legados (seq 1..N pré-G08) não têm o campo
   e permanecem válidos; `parse_event_store` NÃO injeta o campo (ausência ==
   proveniência desconhecida/legada). Quando presente, o bloco é validado:
   dict com `runner_id` string não-vazia, senão `RUNNER_INVALID` (fail-closed).
5. **Versionamento:** a adição é estritamente aditiva e opcional — não quebra
   consumidores 0.4.1. `schema_version` do evento PERMANECE `0.4.1`; o bump
   coordenado para 0.4.2 (contratos + roadmap.schema + docs) fica explicitamente
   adiado para uma release de contratos, evitando ripple em `const` espalhados.
6. **Projeção:** o projector ignora `runner` — proveniência é forense, não
   estado. Replay e hash de projeção permanecem idênticos para stores legados
   (golden test obrigatório no QA).

## PROV-02 — Registro de runners no swarm (opção C)

`agents_swarm.yaml` ganha seção própria (runners não são agents):

```yaml
runners:
  claude-cowork:
    display_name: "Claude (Cowork)"
    kind: "llm-agent"
  human-terminal:
    display_name: "Operador humano via terminal"
    kind: "human"
  unattended:
    display_name: "Execução não atribuída"
    kind: "unknown"
```

`RUNTIME_POLICY.yaml` ganha:

```yaml
runner_validation: "permissive"   # permissive | strict
```

- **permissive** (default): qualquer `runner_id` é aceito e carimbado.
- **strict**: no caminho `submit`, `runner_id` fora da seção `runners` →
  rejeição `RUNNER_UNKNOWN` antes dos workflow gates. Comandos administrativos
  do orchestrator (task create, init, verify) não exigem registro — são do
  operador por definição.

Novos reject codes registrados em `reject_codes.py` (fonte única, M-04):
`RUNNER_INVALID`, `RUNNER_UNKNOWN`.

## Interações com o plano de correção

- **G02 (hash chain):** executar G08 antes — a cadeia nasce cobrindo o bloco.
- **G03 (identidade):** o token/HMAC de G03 deve autenticar o RUNNER;
  o papel (`actor`) é autorização, não autenticação.
- **Acordo híbrido:** edições em `.roadmap/` (swarm, contrato, policy) são
  ações de operador, registradas nas notes do complete de T-005.

## Fora de escopo (follow-up recomendado: G09)

`operator.effect` — evento próprio para ações de operador fora de boundary,
substituindo o registro em prosa nas notes. Decisão adiada para não inflar G08.

## Critérios de aceite

1. Todo evento novo carrega `runner` com `runner_id` resolvido por precedência.
2. Envelope de agente contendo `runner` é rejeitado (schema + forbidden_fields).
3. Store legado parseia e projeta hash idêntico (golden replay).
4. `strict` rejeita runner não registrado com `RUNNER_UNKNOWN`; permissive aceita.
5. Suíte completa verde; inventory test de reject codes verde.
