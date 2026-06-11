# QA G02 — Write-conflict com escopo do run() (M1)

**Task:** T-2012 | **Valida:** T-2011 (impl) contra docs/spec/G02-run-write-conflict.md | **Resultado: APROVADO**

## Evidências

### 1. Cenário de clobber cross-iteração rejeitado (content e edits)

- `tests/test_write_conflict_policy.py::test_single_run_cross_iteration_write_conflict_rejects_second_write`: duas tasks encadeadas (`P-1` → `P-2`) escrevendo `docs/spec/shared.md` em um único `run(steps=None, parallel=1)`. A segunda escrita rejeita com `output.rejected` `error_code=WRITE_CONFLICT`; o conteúdo da primeira sobrevive ao commit; `verify()` ok.
- `tests/test_file_update_edits.py::test_single_run_edit_with_stale_disk_base_is_write_conflict`: a segunda task envia **edits** com `base_sha256` do conteúdo base do disco (que casaria, pois o staging da primeira ainda não commitou). Rejeitada com `WRITE_CONFLICT` — a garantia do `base_sha256` não é mais furada pelo staging pendente.

### 2. Validação red/green (executada na T-2011)

Com o `execution.py` original (sem o fix), ambos os testes **falham** — o clobber silencioso é reproduzido (last-write-wins no commit). Com o fix (`run_write_set` com escopo do `run()` inteiro), ambos passam.

```
# sem fix:  2 failed
# com fix:  19 passed (test_write_conflict_policy.py + test_file_update_edits.py)
```

### 3. Regressões

- `test_parallel_complete_write_conflict_rejects_without_second_side_effect` (dois `run()` separados): **verde** — conflito intra-wave preservado; escrita sequencial no mesmo path **entre** `run()`s continua permitida (pós-commit o `base_sha256` volta a casar).
- Suíte completa: **316 passed** (`PYTHONPATH=src python -m pytest -q`), pós-aplicação governada do fix.

### 4. Auditoria da aplicação

- Fix aplicado pelo Orchestrator via `file_updates` (4 arquivos, evento `orchestrator.file.write` seq ~93), `verify_status: ok` em todo o ciclo.
- Semântica registrada em `src/esaa/templates/AGENT_CONTRACT.yaml` (bloco `semantics` de edits): `base_sha256` valida contra conteúdo commitado em disco; segunda escrita no mesmo path dentro de um `run()` → `WRITE_CONFLICT`.

## Critérios de aceitação da spec

| Critério | Status |
|---|---|
| 1. Clobber cross-iteração rejeitado (content e edits) | OK |
| 2. Regressões verdes (intra-wave e cross-run) | OK |
| 3. Semântica documentada no template | OK |
| 4. Suíte completa verde | OK — 316 passed |

## Observação

Trade-off documentado na spec permanece válido: escritas sequenciais legítimas no mesmo path dentro de um único `run()` agora exigem dois `run()`s. Comportamento fail-closed, recuperação trivial.
