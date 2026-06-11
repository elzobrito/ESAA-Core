# G04 — Especificação: Robustez de Concorrência (locks e retry)

> Tarefa: T-011 (spec) · Targets: SEC-04, ARC-03 · Depende: T-002
> Motivação: dois incidentes REAIS neste workspace em 2026-06-09:
> (1) lock órfão após bloqueio de unlink pelo sandbox — deadlock até remoção
> manual; (2) torn-write no evento 85 com runners concorrentes (claude-cowork
> + codex): evento parcial gravado E lost-write de um task.create aceito.

## Post-mortem do incidente de concorrência (entrada obrigatória do design)

Sequência reconstruída pela proveniência G08: codex emitiu task.create T-007
(seq 83) e verify.start/ok (84/85); claude-cowork emitiu task.create T-008
concorrentemente, recebeu "accepted", mas seus eventos nunca persistiram
(lost-write) e o verify.ok do codex ficou truncado no meio da linha
(torn-write). Causa-raiz: os dois processos rodaram em hosts diferentes
(Windows nativo vs VM montada) onde a atomicidade de O_CREAT|O_EXCL do
lockfile NÃO é garantida pela camada de montagem — o lock mutuamente
exclusivo virou ilusão.

## SEC-04 — Lockfile robusto

1. **Metadados**: lockfile grava JSON `{pid, hostname, runner_id, acquired_at}`
   (runner_id do G08 — o lock identifica QUEM segura).
2. **Liveness local**: mesmo hostname → `os.kill(pid, 0)`; processo morto →
   takeover imediato com log estruturado.
3. **TTL cross-host**: hostname diferente (caso do incidente) → liveness não
   verificável; takeover apenas após `lock_max_age` (default PT2M, em
   RUNTIME_POLICY `concurrency.lock_max_age`).
4. **Takeover auditado**: remove lock órfão e registra warning em stderr +
   métrica `lock_takeovers`; nunca silencioso.
5. **Detecção de torn-write no append**: após escrever, o writer relê a
   própria linha (read-after-write) e confere `event_hash`/bytes antes de
   reportar accepted — converte lost/torn-write em erro explícito
   (`APPEND_VERIFY_FAILED`) em vez de falso sucesso. Custo: 1 read por append.

## ARC-03 — Retry com backoff para STALE_STATE_*

1. `submit` ganha laço de retry interno para `STALE_STATE_SEQ`/`STALE_STATE_HASH`:
   re-parse do store, **revalidação completa** do output contra o estado novo
   (status pode ter mudado — claim de outrem, etc.) e novo append.
2. Config em RUNTIME_POLICY: `concurrency.submit_retries` (default 2) e
   `concurrency.retry_backoff` (PT0.2S exponencial, jitter ±50%).
3. Se a revalidação muda o veredito (ex.: task não está mais em todo),
   NÃO retenta: devolve a rejeição nova imediatamente (sem mascarar).
4. Métricas: `submit_retries`, `stale_conflicts`, `lock_takeovers`,
   `lock_wait_ms` expostas em `metrics`.

## Regra operacional (documentar em readme + CLAUDE.md/AGENTS.md)

Multi-runner simultâneo no MESMO workspace é suportado apenas entre processos
do mesmo host. Cross-host (Windows + VM montada) o lock é melhor-esforço:
recomenda-se um runner por vez até existir lock de serviço (follow-up G09+).

## Critérios de aceite

1. Lock órfão de processo morto (mesmo host) é tomado em <1s.
2. Lock de processo vivo nunca é tomado, mesmo após lock_max_age.
3. Lock cross-host órfão é tomado somente após lock_max_age.
4. Dois submits concorrentes: ambos aceitos via retry OU um rejeitado com
   código estruturado — nunca duplicate seq, nunca torn-write silencioso.
5. Read-after-write detecta truncamento e devolve APPEND_VERIFY_FAILED.
6. Stress multi-processo (mesmo host) preserva seq monotônico e store íntegro.

## Novos códigos

`APPEND_VERIFY_FAILED`, `LOCK_TAKEOVER` (informativo em métricas/logs).
