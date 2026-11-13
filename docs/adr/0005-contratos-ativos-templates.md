---
titulo: "ADR 0005 — Contratos ativos podem divergir dos templates"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0005 — Contratos ativos podem divergir dos templates

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Aceito para a separação existente; registro de hashes proposto para AUD-O2-060.

## Contexto

Os contratos em `.roadmap/` governam o workspace. Os templates empacotados servem à criação de novos workspaces e podem evoluir em outro ritmo. [agentes-esaa](../../AGENTS.md) proíbe sincronizá-los por cópia; [divergencia-contratos](../operations/contract-drift.md) registra as diferenças e suas justificativas.

## Decisão

Manter dois ciclos de vida e migração explícita, seletiva e reversível. [src/esaa/contract_migrate.py:142 — `migrate_active_contracts`](../../src/esaa/contract_migrate.py#L142) altera apenas os schemas admitidos, com backup; [src/esaa/contract_migrate.py:197 — `revert_active_contracts`](../../src/esaa/contract_migrate.py#L197) reverte os admitidos. Não tratar toda divergência como corrupção nem substituir política local automaticamente.

A AUD-O2-060 acrescentará `contract.set` reservado ao Orchestrator: payload com nome/caminho relativo do contrato e SHA-256 dos bytes ativos. Migração, reversão e comando explícito de registro do operador emitirão o evento após a alteração correspondente. O log registrará o hash, não o conteúdo nem segredos. `verify` comparará com o último registro por contrato e informará divergência sem falhar; ausência de registro significa não registrado, não igualdade presumida. Essa observação não restaura contratos passados nem torna a política corrente autenticamente histórica. Detalhes de transação e projeção constam em [adr-0007](0007-plugins-roadmaps-eventos.md).

## Alternativas consideradas

- Copiar sempre os templates sobre o workspace: pode remover autorização e políticas intencionais.
- Nunca migrar: impede adoção explícita de capacidades novas.
- Colocar o conteúdo dos contratos em eventos: amplia armazenamento e exposição; não é a entrega da AUD-O2-060.

## Consequências

A política local continua soberana e diferenças são documentáveis. O registro futuro permite observação objetiva do drift, sem mudar seu status para erro. A responsabilidade por preservar e autorizar conteúdo continua com o proprietário.

## Referências

**Este documento referencia:**

- [divergencia-contratos](../operations/contract-drift.md)
- [src/esaa/contract_migrate.py:142 — `migrate_active_contracts`](../../src/esaa/contract_migrate.py#L142)
- [src/esaa/contract_migrate.py:197 — `revert_active_contracts`](../../src/esaa/contract_migrate.py#L197)
- [adr-0007](0007-plugins-roadmaps-eventos.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado ARQ-06; ARQ-03; tarefa documental AUD-O2-090; implementação: AUD-O2-060 (contract.set); AUD-O1-090 (registro de divergências existente).

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
