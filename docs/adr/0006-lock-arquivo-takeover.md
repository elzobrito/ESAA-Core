---
titulo: "ADR 0006 — Lock por arquivo com O_EXCL e takeover"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0006 — Lock por arquivo com O_EXCL e takeover

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Aceito — comportamento existente.

## Contexto

O runtime é uma CLI sem daemon, com event store em arquivo e suporte a Linux/Windows. [src/esaa/store.py:438 — `_acquire_store_lock`](../../src/esaa/store.py#L438) usa `os.open` com `O_CREAT|O_EXCL|O_WRONLY` e grava PID, hostname, runner e horário. [src/esaa/store.py:564 — `append_transactional`](../../src/esaa/store.py#L564) relê e valida o estado sob o mesmo lock antes do append.

## Decisão

Manter o lock por arquivo e o takeover controlado pela CLI. [src/esaa/store.py:411 — `_should_takeover_lock`](../../src/esaa/store.py#L411) só autoriza takeover local quando o PID não está vivo; outro host ou metadados inválidos dependem de expiração do TTL. [src/esaa/store.py:367 — `_pid_is_alive`](../../src/esaa/store.py#L367) usa consulta de processo no Windows e `os.kill(pid, 0)` no Unix; isso é uma verificação operacional de liveness, não autenticação. [src/esaa/store.py:396 — `_takeover_lock`](../../src/esaa/store.py#L396) registra warning e métrica.

A escrita é conferida por read-after-write em [src/esaa/store.py:487 — `_verify_appended_lines`](../../src/esaa/store.py#L487). Respeitar `STORE_LOCK_TIMEOUT`, `APPEND_VERIFY_FAILED` e falhas de integridade; nunca remover lock manualmente. A concorrência entre processos do mesmo host depende de filesystem com exclusividade real de criação. Compartilhamento entre hosts por montagem não fornece a mesma garantia; manter um escritor por vez nesses ambientes, conforme [g04-concorrencia](../spec/G04-concurrency-robustness.md).

## Alternativas consideradas

- `fcntl`: vínculo com plataforma Unix, sem a mesma interface no Windows, não resolve por si só montagens entre hosts.
- Banco de dados: adiciona serviço/dependência e migração do modelo de armazenamento; não é necessário ao fluxo local em arquivo.
- Lock externo coordenado: opção futura para múltiplos hosts; exige outro componente operacional.
- Remoção manual de lock: pode permitir dois escritores; contraria o protocolo.

## Consequências

A CLI permanece distribuível sem serviço de coordenação. A detecção de falhas de escrita reduz falsos sucessos; não converte armazenamento remoto em transação distribuída. TTL e takeover são decisões operacionais auditáveis, sujeitas às premissas de host e filesystem.

## Referências

**Este documento referencia:**

- [g04-concorrencia](../spec/G04-concurrency-robustness.md)
- [src/esaa/store.py:438 — `_acquire_store_lock`](../../src/esaa/store.py#L438)
- [src/esaa/store.py:564 — `append_transactional`](../../src/esaa/store.py#L564)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado ARQ-06; tarefa documental AUD-O2-090; implementação: comportamento existente (G04).

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
