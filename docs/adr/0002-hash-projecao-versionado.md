---
titulo: "ADR 0002 — Verificação da projeção por lote e versão"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0002 — Verificação da projeção por lote e versão

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Proposto — implementação exclusiva da AUD-O2-070, após AUD-O2-050, AUD-O2-060 e AUD-O2-040.

## Contexto

Hoje [src/esaa/orchestrator_commit.py:16 — `prepare_orchestrator_events`](../../src/esaa/orchestrator_commit.py#L16) acrescenta `verify.start`/`verify.ok` aos lotes. [src/esaa/projector.py:394 — `_apply_event`](../../src/esaa/projector.py#L394) usa `verify.ok` para marcar o estado, sem reconferir seu hash histórico. Isso difere do comando `verify`, que já compara projeções em disco ao replay em [src/esaa/service_core.py:225 — `verify`](../../src/esaa/service_core.py#L225). O hash corrente de referência é calculado por [src/esaa/projector.py:75 — `compute_projection_hash`](../../src/esaa/projector.py#L75); ele não é uma assinatura nem o hash da cadeia de eventos.

## Decisão

1. Eliminar a emissão automática de `verify.start` e `verify.ok` nos cinco caminhos de escrita identificados pela AUD-O2-070. Preservar essas ações e `verify.fail` na leitura de históricos. O comando `verify` permanece somente leitura.
2. O último evento de cada lote não vazio recebe **no topo do envelope**, fora de `payload`, o par `projection_hash_after` (SHA-256 hexadecimal) e `projector_version` (versão inteira positiva). Os campos aparecem juntos, somente no evento final; um lote vazio não emite evento. O Orchestrator calcula o hash após aplicar todos os eventos desse lote. Primeiro calcula a projeção, depois inclui os dois campos, depois calcula os hashes da cadeia: não existe dependência circular.
3. Usar a mesma função e o mesmo domínio do hash atual de projeção. Os novos campos não entram no conteúdo projetado nem alteram o hash de fixtures antigas. Os locks adicionais de [adr-0007](0007-plugins-roadmaps-eventos.md) ficam fora desse domínio. A versão do projetor é uma constante própria, independente de `PACKAGE_VERSION`, iniciada em 1; incrementa somente quando muda a saída canônica coberta pelo hash. Mudanças de metadados de verificação, que estão fora desse domínio, não exigem incremento.
4. AUD-O2-070 incrementa `SCHEMA_VERSION`, acrescenta o par ao schema de evento preparado na AUD-O2-050 e adiciona upcaster. Eventos antigos permanecem sem hash e sem versão do projetor: é proibido inventar compromisso retroativo ou regravar o log real.
5. No replay, ao chegar ao evento final, reconferir o hash somente se `projector_version` for igual à constante corrente. Igualdade confirma o lote; divergência levanta `PROJECTION_DRIFT` com `event_seq`, hash esperado e calculado. `verify` retorna `verify_status=mismatch` e exit code 2 nesse caso. Versão anterior fica como não reconferida, mesmo com hash diferente. Versão futura do formato não suportada falha explicitamente, sem interpretação silenciosa; não é tratada como versão anterior.
6. Na verificação normal sem snapshot validado, reconferir o último lote com compromisso. Quando houver snapshot validado, reconferir todos os lotes posteriores a ele, incluindo o último uma única vez. `verify --full` reconfere todos os lotes com versão corrente. Um lote elegível é contado uma única vez. Não voltar a replay de todo o prefixo a cada evento: aplicar incrementalmente e usar resumo da projeção. O cenário de 50 mil eventos precisa satisfazer o limite de 3 s para claim e verify definido na AUD-O2-070.
7. A resposta expõe `hash_checked` (lotes efetivamente reconferidos) e `hash_unchecked` (compromissos de versão anterior ou omitidos pela leitura abreviada). Eventos legados sem compromisso não contam como lotes não reconferidos; sua ausência é informada como histórico legado, sem simular comprovação. `verify_status=ok` significa ausência de divergência nos compromissos reconferidos e projeções em disco coerentes; não significa que todo o histórico tem compromisso. Divergência das projeções em disco continua sendo mismatch.
8. Pares históricos continuam válidos e mantêm o significado legado; um log misto é normal. `verify.fail` explícito conserva seu tratamento. AUD-O2-070 deve ajustar clear, snapshot, compactação e atualização de hashes para deixar de procurar o último `verify.ok`; documenta atualização e falha fechada de leitores antigos.

## Alternativas consideradas

- Reconferir todo hash com todo projetor futuro: invalida históricos quando a saída muda.
- Usar versão do pacote como versão do projetor: invalida verificações em releases sem alteração de projeção.
- Manter dois eventos extras por lote: conserva volume sem acrescentar comprovação histórica.
- Recalcular o hash de todo prefixo em cada evento: reintroduz custo quadrático.

## Consequências

A verificação passa a detectar drift entre o compromisso gravado e o projetor da mesma versão, com cobertura explicitada. Leitores antigos precisam de atualização para o novo formato. Não há migração destrutiva do histórico; compromissos antigos não se tornam falsamente verificáveis. Esta decisão é alvo, não garantia implementada nesta tarefa.

## Referências

**Este documento referencia:**

- [src/esaa/submission.py:120 — `submit`](../../src/esaa/submission.py#L120)
- [src/esaa/service_core.py:78 — `init`](../../src/esaa/service_core.py#L78)
- [src/esaa/orchestrator_commit.py:107 — `refresh_verification_hashes`](../../src/esaa/orchestrator_commit.py#L107)
- [adr-0008](0008-schema-append-upcasters.md)
- [adr-0007](0007-plugins-roadmaps-eventos.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado FUN-04; ARQ-06; tarefa documental AUD-O2-090; implementação: AUD-O2-070 (formato/verificação); AUD-O2-050 (schema/upcaster).

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
