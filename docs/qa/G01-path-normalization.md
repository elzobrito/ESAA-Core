# QA G01 — Normalização de paths (M2)

**Task:** T-2002 | **Valida:** T-2001 (impl) contra docs/spec/G01-path-normalization.md | **Resultado: APROVADO**

## Evidências

### 1. Suíte completa (pós-aplicação governada do fix)

```
PYTHONPATH=src python -m pytest -q
314 passed
```

299 testes pré-existentes + 15 novos em `tests/test_path_normalization.py`. Nenhum teste dependia do comportamento antigo do `lstrip` (zero correções necessárias na suíte).

### 2. Sondas empíricas (matriz da spec)

```
'.gitignore'            -> '.gitignore'            (dotfile preservado)
'../x'                  -> '../x'                  (traversal preservado p/ rejeição)
'.roadmap/lessons.json' -> '.roadmap/lessons.json' (forbidden_write .roadmap/** agora casa)
'./docs/a.md'           -> 'docs/a.md'             (prefixo ./ removido)
'a\\b.md'                -> 'a/b.md'                (backslash convertido)
'/abs/x'                -> '/abs/x'                (absoluto preservado p/ rejeição)
'docs/.draft.md'        -> 'docs/.draft.md'        (dotfile em subdir preservado)
```

### 3. Rejeições nos fluxos governados (testes automatizados)

- content `../x` → `BOUNDARY_VIOLATION`; content/edits `.roadmap/lessons.json` → `BOUNDARY_VIOLATION` (via submit).
- edits `../x` standalone (`resolve_edit_updates`) → `EDIT_INVALID`.
- Nota de precisão sobre a matriz da spec: no fluxo governado via `submit`, a validação de boundary roda **antes** da resolução de edits, então `../x` com edits rejeita com `BOUNDARY_VIOLATION` (não `EDIT_INVALID`); o `EDIT_INVALID` aplica-se à API standalone. O critério de aceitação 4 da spec ("ambos rejeitam, com códigos próprios de cada fluxo") está satisfeito.
- edits em dotfile dentro do boundary (`docs/.draft.md`) resolvem contra o arquivo correto (sem retargeting).

### 4. Higiene

- `ruff check` e `black --check` em `src/esaa/utils.py` e `tests/test_path_normalization.py`: passed.
- `lstrip("./")` ausente de `src/esaa/utils.py`.
- O próprio fix foi aplicado pelo Orchestrator via file_update no **formato edits** (base_sha256 + old_string/new_string) — dogfooding do mecanismo da v0.4.1 em produção, com `verify_status: ok` (seq 65).

## Critérios de aceitação da spec

| Critério | Status |
|---|---|
| 1. Matriz coberta por testes automatizados | OK — 15 testes |
| 2. Suíte completa verde | OK — 314 passed |
| 3. Sem lstrip('./') em utils.py | OK |
| 4. Assimetria content/edits eliminada | OK — com nota de precisão acima |
