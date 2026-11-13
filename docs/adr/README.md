---
titulo: "Decisões arquiteturais centrais do ESAA-Core"
tipo: "Índice"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# Decisões arquiteturais centrais do ESAA-Core

**Sumário:** Decisões · Uso e limites · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## 1. Decisões

Base inspecionada: esaa-core 0.5.0b29, branch `audit/onda-0`. Linhas nas referências são âncoras dessa base; as funções identificam a fonte mesmo após deslocamentos. Os estados abaixo distinguem comportamento observado de decisões alvo. Nenhum ADR desta entrega altera código ou ativa um modo opcional.

| ADR | Decisão | Estado |
|---|---|---|
| 0001 | [Identidade de ator inativa por padrão](0001-identidade-opt-in.md) | Aceito |
| 0002 | [Verificação da projeção por lote e versão](0002-hash-projecao-versionado.md) | Proposto |
| 0003 | [Cadeia de hash opcional e sem chave](0003-cadeia-opcional-sem-chave.md) | Aceito |
| 0004 | [Artifacts de efeitos fora do Git](0004-artifacts-fora-git.md) | Aceito |
| 0005 | [Contratos ativos podem divergir dos templates](0005-contratos-ativos-templates.md) | Aceito |
| 0006 | [Lock por arquivo com O_EXCL e takeover](0006-lock-arquivo-takeover.md) | Aceito |
| 0007 | [Plugins e roadmaps projetados a partir do log](0007-plugins-roadmaps-eventos.md) | Proposto |
| 0008 | [Validação no append e compatibilidade por upcasters](0008-schema-append-upcasters.md) | Proposto |

## 2. Uso e limites

Os ADRs 0002, 0007 e 0008 definem respectivamente as implementações AUD-O2-070, AUD-O2-060 e AUD-O2-050. A cadeia de implementação é 050 → 060 → 070; a 070 também depende da 040. O ADR 0005 mantém a separação existente entre contratos ativos e templates, com registro de hashes ainda proposto na 060.

Padrões permissivos são escolhas arquiteturais com custos e benefícios explícitos. O índice não transforma proposta em garantia entregue. A política de suporte está em [seguranca-esaa](../../SECURITY.md) e a rotina operacional em [backup-artifacts](../operations/artifact-backup.md). Metadados e histórico deste documento registram autoria da proposta; revisão e aprovação seguem o Orchestrator.

## Referências

**Este documento referencia:**

- [adr-0001](0001-identidade-opt-in.md) — Identidade de ator inativa por padrão.
- [adr-0002](0002-hash-projecao-versionado.md) — Verificação da projeção por lote e versão.
- [adr-0003](0003-cadeia-opcional-sem-chave.md) — Cadeia de hash opcional e sem chave.
- [adr-0004](0004-artifacts-fora-git.md) — Artifacts de efeitos fora do Git.
- [adr-0005](0005-contratos-ativos-templates.md) — Contratos ativos podem divergir dos templates.
- [adr-0006](0006-lock-arquivo-takeover.md) — Lock por arquivo com O_EXCL e takeover.
- [adr-0007](0007-plugins-roadmaps-eventos.md) — Plugins e roadmaps projetados a partir do log.
- [adr-0008](0008-schema-append-upcasters.md) — Validação no append e compatibilidade por upcasters.

- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — origem dos achados.
- [seguranca-esaa](../../SECURITY.md) — reporte e compatibilidade.
- [backup-artifacts](../operations/artifact-backup.md) — backup dos bytes de efeitos.

**Este documento é referenciado por:**

- ADRs 0001 a 0008 — retorno ao índice.
