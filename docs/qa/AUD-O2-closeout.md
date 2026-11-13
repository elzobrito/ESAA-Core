# Fechamento QA — Onda 2 (`AUD-O2`)

- **Data:** 2026-11-12
- **Branch:** `audit/onda-0`
- **Ambiente de referência:** `Python 3.14.4 | Linux x86_64`

---

## 1. Matriz de Tarefas da Onda 2

| Tarefa | Achado de origem | Critério / Entrega principal | Evidência verificada |
| :--- | :--- | :--- | :--- |
| `AUD-O2-010` | `UTL-01`, `CLI` | `chain verify` equivalente a `verify --chain`; `status` somente leitura; `dispatch-context` retorna `next_command` / `next_command_argv` aceito em `--dry-run` | `tests/test_onda2_properties.py::test_cli_cross_checks_dispatch_status_chain_and_oplog` (`8 passed`), suite completa verde |
| `AUD-O2-020` | `PRO`, `CLI` | Semântica e paridade de comandos de inspeção / status somente leitura | `tests/test_onda2_properties.py`, suite completa verde |
| `AUD-O2-030` | `CLI` | `--help` completo e flags documentadas em toda a CLI | `tests/test_cli_help.py`, `tests/test_onda2_properties.py` |
| `AUD-O2-040` | `ARQ-01` | Replay incremental por snapshot (`create_snapshot` / `load_verified_replay`) preservando projeções idênticas ao replay completo | `tests/test_snapshot_replay.py`, `tests/test_onda2_properties.py::test_snapshot_replay_equals_full_replay_at_arbitrary_cuts` |
| `AUD-O2-050` | `MOD-01`, `ARQ-02` | `event.schema.json` por ação no append; upcasters `v0.5.0b19..v0.5.0b25`; replay histórico sem bloqueio de schema de append | `tests/test_event_upcast.py`, `tests/test_onda2_properties.py::test_append_rejects_invalid_schema_while_replay_allows_historical` |
| `AUD-O2-060` | `MOD-02` | `plugin.*`, `roadmap.*`, `contract.set` orientados a eventos; reconstrução byte a byte de `plugins.lock.json` e `roadmaps.lock.json` | `tests/test_plugin_events.py`, `tests/test_onda2_properties.py::test_plugin_locks_reconstructed_byte_for_byte_by_project` |
| `AUD-O2-070` | `ARQ-03` | `SCHEMA_VERSION = "0.4.2"`, remoção de `verify.start`/`verify.ok` automáticos, `projection_hash_after` + `projector_version` inline e `PROJECTION_DRIFT` | `tests/test_projection_hash_inline.py`, `tests/test_onda2_properties.py::test_mixed_legacy_and_v042_log_verifies_and_detects_drift` |
| `AUD-O2-080` | `ARQ-05` | `store.py` como I/O puro via `StoreHooks`, composição em `store_runtime.py`, `cli.main` com tabela de despacho `CLI_HANDLERS` (`C901 <= 15`) e `_plugin_status` movido para `plugins.py` | `tests/test_store_layering.py`, `ruff check --select C901 --config 'lint.mccabe.max-complexity=15'`, `mypy src/esaa` (`0 issues`) |
| `AUD-O2-090` | `DOC` | Revisão de guias e referências documentais | Concluída (`done`); pendência editorial menor registrada em `ISS-AUD-O2-090-EDITORIAL-20261112` |
| `AUD-O2-095` | `UTL-03`, `UTL-02` | `src/esaa/py.typed` empacotado, Python `3.14` no CI e `classifiers`, levantamento de dependências demo (`stdlib` apenas -> sem extra vazio), marcação `[demo]` no `--help` | `tests/test_packaging_extras.py`, `python3 -m build` + `twine check` (`PASSED`) |
| `AUD-O2-100` | `ENG-04` | `src/esaa/oplog.py` (`ESAA_LOG`) com escrita atômica `O_APPEND` fora do lock, métricas `lock_retries` e `events_appended` em `store.py` | `tests/test_oplog.py` (`6 passed`), `docs/guides/esaa-cli-reference.md` |
| `AUD-O2-110` | `SEC` | Ativação de identidade no próprio repositório (operada pelo proprietário) | **Não executada nesta onda** — aguarda pré-condições em `ISS-AUD-O2-110-PRECONDITIONS-20261112` |

---

## 2. Benchmark Sintético (`ARQ-01` vs Pós-Onda 2)

Medições realizadas em `Python 3.14.4 | Linux x86_64` com eventos sintéticos `runner.metrics` em `/tmp`:

| Escala (`N` eventos) | Snapshot | `project` | `verify` | `eligible` | `task_create` | `claim` |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `50 000` (Baseline `ARQ-01`) | — | — | `22.0000 s` | — | — | `75.0000 s` |
| `2 000` | — | `0.0345 s` | `0.0346 s` | `0.0651 s` | `0.1651 s` | `0.2169 s` |
| `10 000` | — | `0.1867 s` | `0.1826 s` | `0.3440 s` | `0.7746 s` | `0.8397 s` |
| `50 000` | — | `0.9501 s` | `1.0169 s` | `1.8031 s` | `3.9468 s` | `4.1921 s` |
| `200 000` | `before=190 000` | `0.1814 s` | `0.1942 s` | `4.7015 s` | *(issue aberta)* | `8.3612 s` |

Observações:
- `verify` em `50 000` caiu de `22 s` para `1.0169 s` (`~21.6x` mais rápido, `< 3 s`).
- `verify` em `200 000` com snapshot em `190 000` executou em `0.1942 s` (`< 3 s`), e `project` em `0.1814 s`.
- `claim` em `50 000` caiu de `75 s` para `4.1921 s` (`~17.9x` mais rápido); permanece acima de `3 s` sem snapshot porque `claim_task` ainda lê o log fora de `append_transactional` (já rastreado em `ISS-AUD-O2-040-SCOPE-20261112`).

---

## 3. Tamanho do Log (Eventos por Comando)

| Comando | Antes da Onda 2 | Depois da Onda 2 | Motivo |
| :--- | :--- | :--- | :--- |
| `claim` | 3 (`claim` + `verify.start` + `verify.ok`) | **1** (`claim` com `projection_hash_after`) | `AUD-O2-070` eliminou pares `verify.*` automáticos |
| `complete` | 3 (`complete` + `verify.start` + `verify.ok`) | **1** (`complete` com `projection_hash_after`) | Idem |
| `review` | 3 (`review` + `verify.start` + `verify.ok`) | **1** (`review` com `projection_hash_after`) | Idem |
| `task create` | 3 (`task.create` + `verify.start` + `verify.ok`) | **1** (`task.create` com `projection_hash_after`) | Idem |

---

## 4. Log Real do Repositório

- **Estado verificado ao final da `AUD-O2-095` (antes do `claim` da `AUD-O2-120`):**
  - `verify_status`: `ok`
  - `last_event_seq`: `2273` (`2275` após `complete`+`review` da `AUD-O2-095`)
  - `projection_hash_sha256` (`seq 2275`): obtido de forma determinística pelo replay completo com upcast `0.4.1 -> 0.4.2` (`AUD-O2-070`) e projeção de estado atualizada pelas tarefas `AUD-O2-010..095`.
- A diferença de `projection_hash_sha256` ao longo da onda decorre exclusivamente dos novos eventos de ciclo de vida das tarefas `AUD-O2-*` e da migração de `SCHEMA_VERSION` para `0.4.2` (`AUD-O2-070`).

---

## 5. Fora de Escopo e Issues Abertas

- **Fora de escopo:** redução de complexidade C901 em `validate_plugin_dir`, `validate_identity_history`, `_apply_task_amend`, `run`; remoção de comandos/flags demo; movimentação de saída de `hotfix` ou `tools/audit`; ativação de identidade (`AUD-O2-110`); bump de `PACKAGE_VERSION` e `CHANGELOG.md` (`AUD-O2-130`).
- **Issues abertas na Onda 2:**
  - `ISS-AUD-O2-040-SCOPE-20261112`: integração do snapshot incremental em consumidores adicionais (`claim`, `eligible`, etc.).
  - `ISS-AUD-O2-050-HISTORICAL-RUNNER-20261112`, `ISS-AUD-O2-050-SCOPE-20261112`, `ISS-AUD-O2-050-TEST-SCOPE-20261112`, `ISS-AUD-O2-050-VERIFICATION-SCOPE-20261112`: acompanhamentos da validação de schema por ação.
  - `ISS-AUD-O2-090-EDITORIAL-20261112`: referência editorial remanescente no guia de backup.
  - `ISS-AUD-O2-110-PRECONDITIONS-20261112`: pré-condições para ativação de identidade assistida pelo proprietário.
  - `ISS-AUD-O2-120-SNAPSHOT-HASH-20261112`: `create_task` após `create_snapshot` falha com `CorruptedStoreError: projection_hash_after mismatch` (reproduzível com 200 eventos e `create_snapshot(before=100)`).
