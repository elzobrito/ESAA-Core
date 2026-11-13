---
titulo: "ADR 0004 — Artifacts de efeitos fora do Git"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0004 — Artifacts de efeitos fora do Git

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Aceito — comportamento existente; mitigação operacional documentada nesta tarefa.

## Contexto

O Git ignora `.roadmap/artifacts/` e `.roadmap/artifacts/file-effects/`, conforme [gitignore-esaa](../../.gitignore). Os metadados de efeito ficam no evento `orchestrator.file.write`, mas os bytes completos ficam em artifacts JSON e, para binários, em blobs referenciados por hash ([src/esaa/file_effects.py:347 — `write_artifact`](../../src/esaa/file_effects.py#L347), [src/esaa/file_effects.py:389 — `verify_artifact`](../../src/esaa/file_effects.py#L389)).

## Decisão

Manter esses artifacts fora do Git para evitar crescimento do repositório com versões completas de cada efeito e de blobs binários. A trilha de recuperação de bytes é local à máquina até que o operador a replique por backup. Um clone preserva os eventos versionados, mas não os artifacts: [src/esaa/file_effects.py:460 — `recover_file_effects`](../../src/esaa/file_effects.py#L460) pode registrar `ARTIFACT_MISSING` mesmo se o arquivo final já existir, pois lê e valida o artifact antes de conferir o destino.

Adotar [backup-artifacts](../operations/artifact-backup.md) para arquivar a árvore inteira, com manifesto SHA-256, restore validado e ensaio de recuperação. O log e os contratos precisam de backup coerente próprio; o arquivo de artifacts não os substitui. Não recriar artifacts de eventos passados com bytes atuais sem prova.

## Alternativas consideradas

- Versionar todos os artifacts no Git: aumenta volume e expõe cópias históricas dos dados a quem recebe o clone.
- Confiar apenas no arquivo final: não preserva versões nem o artifact canônico de cada efeito.
- Regenerar o artifact perdido a partir de metadados: hashes não permitem reconstruir bytes.

## Consequências

Clonagem e reprojeção de estado continuam distintas da recuperação de efeitos. Retenção, confidencialidade e disponibilidade dos backups passam a ser responsabilidade operacional explícita. Sem backup dos bytes, a recuperação correspondente pode ser impossível; a limitação deve ser registrada, sem alterar o log.

## Referências

**Este documento referencia:**

- [gitignore-esaa](../../.gitignore)
- [src/esaa/file_effects.py:445 — `read_artifact`](../../src/esaa/file_effects.py#L445)
- [backup-artifacts](../operations/artifact-backup.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado DOC-04; ARQ-06; tarefa documental AUD-O2-090; implementação: AUD-O2-090 (guia de backup).

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
