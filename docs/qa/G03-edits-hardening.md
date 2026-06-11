# QA G03 - Hardening de edits e docs de semantica (B2, B3, B5)

**Task:** T-2022  
**Valida:** T-2021 contra docs/spec/G03-edits-hardening.md  
**Resultado:** APROVADO

## Evidencias

### 1. API standalone falha fechado

`src/esaa/edits.py` valida o branch sem `edits` e sem `content` com erro estruturado:

- `src/esaa/edits.py:64` emite `ESAAError("SCHEMA_INVALID", ...)`.
- `tests/test_file_update_edits.py:193` cobre `exc.value.code == "SCHEMA_INVALID"`.

### 2. Semantica dual de resource limits documentada

`src/esaa/validator.py` documenta que, no fluxo governado, os edits sao resolvidos antes de `validate_file_update_resource_limits`, portanto o limite mede o conteudo expandido. O branch standalone preserva a aproximacao por `old_string + new_string`.

### 3. CRLF/UTF-8 documentado

As fontes operacionais trazem a regra de match contra texto UTF-8 com newlines exatos:

- `AGENTS.md`
- `.claude/CLAUDE.md`
- `src/esaa/templates/AGENT_CONTRACT.yaml`

O contrato vivo tambem foi sincronizado quanto a semantica de `base_sha256`, `WRITE_CONFLICT` no mesmo `run()` e `old_string`/UTF-8:

- `.roadmap/AGENT_CONTRACT.yaml`

### 4. Testes executados

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_file_update_edits.py tests/test_path_normalization.py -q
```

Resultado:

```text
30 passed in 17.79s
```

## Conclusao

T-2021 atende os criterios de aceite de G03. A unica observacao operacional e que a escrita de `AGENTS.md` e `.claude/CLAUDE.md` exigiu boundary temporario, conforme previsto na spec; esse boundary deve ser revertido no gate final G05.
