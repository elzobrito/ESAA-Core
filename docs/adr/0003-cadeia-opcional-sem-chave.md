---
titulo: "ADR 0003 — Cadeia de hash opcional e sem chave"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0003 — Cadeia de hash opcional e sem chave

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Aceito — comportamento existente.

## Contexto

A cadeia não é exigida para iniciar um workspace. [src/esaa/store.py:204 — `init_hash_chain`](../../src/esaa/store.py#L204) grava uma âncora do prefixo e [src/esaa/store.py:163 — `_prepare_events_for_append`](../../src/esaa/store.py#L163) encadeia os eventos seguintes. [src/esaa/store.py:119 — `compute_event_hash`](../../src/esaa/store.py#L119) calcula SHA-256 de uma representação canônica sem o próprio `event_hash`. Não há segredo nesse cálculo.

## Decisão

Manter ativação explícita, independente da extensão de identidade. [src/esaa/store.py:135 — `_validate_hash_chain`](../../src/esaa/store.py#L135) verifica a âncora do prefixo e a sequência de hashes seguintes; [src/esaa/store.py:188 — `verify_hash_chain`](../../src/esaa/store.py#L188) informa o estado. Sem `chain.anchor`, a anotação é `chain_status=unanchored`, preservando `verify_status=ok` quando o restante está coerente ([src/esaa/verify_annotations.py:23 — `chain_status`](../../src/esaa/verify_annotations.py#L23)).

A cadeia detecta corrupção e edição acidental ou alteração que não recalcule os elos. Ela **não autentica autoria nem impede reescrita por quem pode substituir o log e recalcular âncora e cadeia**. Uma garantia contra esse adversário exige autoridade externa protegida, conforme [adr-0001](0001-identidade-opt-in.md) e [modelo-ameacas](../security/threat-model.md).

## Alternativas consideradas

- Cadeia obrigatória: altera o padrão e o custo de adoção para todos os workspaces.
- Hashes com chave compartilhada: introduzem gestão de segredo e outro modelo de autoridade.
- Confundir cadeia local com assinatura ou pin externo: atribui uma proteção que ela não fornece.

## Consequências

O operador escolhe a integridade adicional sem quebrar logs anteriores. `unanchored` é um estado arquitetural suportado, não um defeito. Cadeia quebrada deve interromper a operação; a solução não consiste em editar o histórico nem remover a âncora.

## Referências

**Este documento referencia:**

- [src/esaa/store.py:135 — `_validate_hash_chain`](../../src/esaa/store.py#L135)
- [src/esaa/verify_annotations.py:23 — `chain_status`](../../src/esaa/verify_annotations.py#L23)
- [adr-0001](0001-identidade-opt-in.md)
- [modelo-ameacas](../security/threat-model.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado ARQ-06; tarefa documental AUD-O2-090; implementação: comportamento existente.

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
