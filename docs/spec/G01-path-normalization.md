# G01 — Normalização de paths (M2)

## Problema

`normalize_rel_path` (src/esaa/utils.py:27) usa `path.replace("\\", "/").lstrip("./")`. `str.lstrip` remove um **conjunto de caracteres** ('.', '/'), não um prefixo. Efeitos confirmados empiricamente:

- `'.gitignore'` → `'gitignore'` (retargeting silencioso de dotfiles)
- `'.roadmap/activity.jsonl'` → `'roadmap/activity.jsonl'` (o `forbidden_write: ".roadmap/**"` do contrato nunca casa)
- `'../x'` → `'x'` (traversal "normalizado" em vez de rejeitado; assimetria com o fluxo edits, que rejeita `'../x'` com `EDIT_INVALID` em edits.py:18)

Na prática o sistema falha fechado (allowlist positiva + base_sha no path errado), mas o retargeting é silencioso e a defesa `.roadmap/**` é decorativa.

## Semântica alvo

1. Converter `'\\'` em `'/'`.
2. Remover apenas prefixos `'./'` repetidos (`'./docs/a.md'` → `'docs/a.md'`; `'./././x'` → `'x'`).
3. Preservar todo o resto: dotfiles (`'.gitignore'`), `'..'` inicial (`'../x'` → `'../x'`), paths absolutos (`'/abs'` → `'/abs'`).

Implementação de referência:

```python
def normalize_rel_path(path: str) -> str:
    norm = path.replace("\\\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm
```

## Efeitos esperados nos validadores

- `validator._validate_safe_path` (validator.py:96-105): `'../x'` agora chega com `'..'` e é rejeitado com `BOUNDARY_VIOLATION`; `'/abs'` idem. Elimina a assimetria com edits.
- `validator._validate_boundaries`: `'.roadmap/**'` em `forbidden_write` passa a casar de verdade (defesa real, em profundidade).
- `edits._workspace_path` (edits.py:14-23): dotfiles preservados; rejeição de `'..'` inalterada (já era estrita).
- `conflicts.normalize_write_set` e `submission._normalize_file_updates`: paths fiéis ao input do agente.
- `external_effects._safe_relative_path` (external_effects.py:129): possui checks próprios de `'..'` e `':'`; sem mudança funcional.

## Matriz de testes (tests/test_path_normalization.py)

| Input | normalize_rel_path | Fluxo content (submit) | Fluxo edits (submit) |
|---|---|---|---|
| `.gitignore` | `.gitignore` (preservado) | — | — |
| `../x` | `../x` (preservado) | `BOUNDARY_VIOLATION` | `EDIT_INVALID` |
| `./docs/a.md` | `docs/a.md` | aceito (boundary ok) | aceito |
| `a\\b.md` | `a/b.md` | — | — |
| `.roadmap/lessons.json` | `.roadmap/lessons.json` | `BOUNDARY_VIOLATION` | `BOUNDARY_VIOLATION` |
| `docs/.draft.md` (task spec) | preservado | aceito | edits resolvem contra o arquivo correto |

## Critérios de aceitação

1. Todos os casos da matriz cobertos por testes automatizados em `tests/test_path_normalization.py`.
2. Suíte completa verde (`PYTHONPATH=src python -m pytest -q`); testes que dependiam do lstrip antigo corrigidos na própria T-2001.
3. Nenhum uso restante de `lstrip("./")` em `src/esaa/utils.py`.
4. Assimetria content/edits para `'../'` eliminada (ambos rejeitam, com códigos próprios de cada fluxo).
