---
titulo: "ADR 0008 — Validação no append e compatibilidade por upcasters"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0008 — Validação no append e compatibilidade por upcasters

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Proposto — implementação exclusiva da AUD-O2-050; extensão de formato na AUD-O2-070.

## Contexto

O normalizador atual [src/esaa/compat.py:6 — `normalize_legacy_event`](../../src/esaa/compat.py#L6) adapta eventos antigos. Regras novas do projetor ainda são executadas no replay; [src/esaa/projector.py:19 — `_new_task`](../../src/esaa/projector.py#L19) usa `legacy=True` para caminhos históricos. Aplicar critérios novos de admissão a fatos já publicados pode impedir a reconstrução de históricos válidos.

## Decisão

1. Criar schema empacotado `event.schema.json` com envelope corrente e payload por ação, cobrindo exatamente `CANONICAL_ACTIONS`. Validar eventos novos em ponto único do store, antes de qualquer gravação do lote, artifact persistente ou efeito final. Preparar os eventos em memória antes dessa validação; a ordem de preparação dos cinco caminhos deve impedir que um callback grave artifacts antecipadamente. Os cinco caminhos de escrita devem passar por esse ponto. A validação considera o lote inteiro: um evento inválido não pode deixar linhas anteriores ou efeitos parciais desse lote.
2. A função de schema valida **somente no append**; parse, replay, materialize, project e verify não chamam o schema corrente por ação. As checagens históricas de integridade (JSONL, sequência, IDs, ações reconhecidas, representação de identidade, cadeia e confiança aplicáveis) continuam valendo. A separação não autoriza aceitar história corrompida nem ignora transições de domínio; impede aplicar regras novas de admissão aos payloads antigos.
3. Fazer de `compat.py` um registro ordenado `schema_version -> (next_version, upcaster)`. Cada upcaster é função pura que devolve uma nova representação em memória, sem escrever no arquivo e sem inventar fatos. Aplicar a cadeia antes de projetar, até a versão corrente. Eventos já correntes passam intactos; invocar a normalização novamente mantém o mesmo resultado. Detectar ciclos e ausência de rota; versão futura/desconhecida falha com erro claro de versão incompatível, sem replay silencioso.
4. A primeira etapa incorpora a transformação existente de v0.3 (`data` para `payload`, `run.init` para `run.start`, status inicial) sem alterar seu resultado semântico. Eventos sem versão entram pela regra legada explícita existente. Versões intermediárias compatíveis têm passos de identidade explícitos. AUD-O2-050 não muda `SCHEMA_VERSION`, não adiciona ações de plugins e não remove usos existentes de `legacy=True`; adapta o mecanismo ao formato corrente 0.4.1. AUD-O2-070 fará o bump e a extensão de [adr-0002](0002-hash-projecao-versionado.md), sem sintetizar hashes para eventos antigos.
5. `validate_event_for_append` produz ESAAError com código próprio, ação e caminho do campo; o schema descreve somente formato corrente. Se uma fixture histórica não se adequar depois do upcast, corrigir o upcaster ou o schema, sem reescrever a fixture ou afrouxar indiscriminadamente a admissão nova. A validação dessas fixtures contra o schema é teste de desenvolvimento, não requisito do replay em runtime.
6. Gerar fixtures executando cada versão publicada em venv isolado fora do checkout, com roteiro fixo de init, task create, claim, complete, review, issue report e hotfix. Versionar o roteiro e instruções junto aos logs, com hash de projeção esperado fixado por versão. Nunca escrever logs à mão ou atualizar o esperado com o projetor novo para esconder drift. Usar tags disponíveis e wheels PyPI para versões sem tag; omissão exige justificativa explícita nos checks. Comparar o resultado da versão produtora e do replay corrente. Não instalar releases históricas no ambiente do repositório.
7. Testes obrigatórios: cada fixture mantém o golden hash; schema cobre cada ação; evento inválido em cada caminho de escrita deixa log/efeitos intactos; replay aceita evento histórico fora do schema corrente sem chamar o validador de ação; cadeia é idempotente no corrente; log real mantém sequência e hash. Mudanças futuras de formato passam por novo upcaster e fixture, não por novos atalhos `legacy=True`.

## Alternativas consideradas

- Validar todos os payloads históricos pelo schema mais novo: torna regras de admissão retroativas.
- Afrouxar todo schema para aceitar qualquer versão: perde precisão para eventos novos.
- Regravar logs durante atualização: destrói bytes e evidência histórica.
- Multiplicar flags legacy pelo projetor: dispersa regras de compatibilidade sem fronteira de versão explícita.

## Consequências

Fatos publicados continuam reprojetáveis enquanto a admissão corrente ganha validação explícita. Upcasters concentram transformações de formato e fixtures documentam a garantia. Não há dispensa de integridade ou de testes, nem promessa de validar fatos antigos por regras futuras. Esta tarefa não implementa os módulos citados como alvo.

## Referências

**Este documento referencia:**

- [src/esaa/store.py:163 — `_prepare_events_for_append`](../../src/esaa/store.py#L163)
- [src/esaa/store.py:257 — `parse_event_store_text`](../../src/esaa/store.py#L257)
- [src/esaa/store.py:500 — `append_events`](../../src/esaa/store.py#L500)
- [src/esaa/store.py:564 — `append_transactional`](../../src/esaa/store.py#L564)
- [src/esaa/compat.py:6 — `normalize_legacy_event`](../../src/esaa/compat.py#L6)
- [adr-0002](0002-hash-projecao-versionado.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado ARQ-04; ARQ-06; tarefa documental AUD-O2-090; implementação: AUD-O2-050 (schema/upcasters/fixtures); AUD-O2-070 (novo formato).

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
