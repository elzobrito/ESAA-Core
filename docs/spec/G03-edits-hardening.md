# G03 — Hardening de edits e docs de semântica (B2, B3, B5)

## B3 — API standalone frágil em resolve_edit_updates

**Problema:** em `src/esaa/edits.py:61-63`, um item de `file_update` sem `edits` é repassado adiante sem validar a presença de `content`. No fluxo governado isso é inalcançável (o `oneOf` do `agent_result.schema.json` barra antes, com `SCHEMA_INVALID`), mas chamadas standalone de `resolve_edit_updates` estouram `KeyError` cru em `submission._normalize_file_updates` (submission.py:12) — falha não estruturada, fora do vocabulário de reject codes.

**Correção:** no branch sem `edits`, validar presença de `content`:

```python
if "edits" not in item:
    if "content" not in item:
        raise ESAAError("SCHEMA_INVALID", f"file_update requires content or edits: {item.get('path')}")
    resolved.append(dict(item))
    continue
```

`SCHEMA_INVALID` já está registrado em `reject_codes.py` — nenhum código novo.

**Teste:** standalone em `tests/test_file_update_edits.py` — item só com `path` → `ESAAError` com `code == "SCHEMA_INVALID"` (não `KeyError`).

## B2 — Semântica dual de _file_update_size

**Fato:** no fluxo governado, os resource limits rodam **após** a resolução de edits (`submit` e `_accept_agent_output` chamam `_normalize_file_updates` antes de `validate_file_update_resource_limits`), conforme o contrato ("resolve antes de external effects, resource limits, staging"). Portanto o branch de `edits` em `_file_update_size` (validator.py:59-65) é código morto no fluxo governado — ele mede `old_string`+`new_string` e só serve a chamadas standalone pré-resolução. Medir o conteúdo expandido é o comportamento correto e mais seguro (um edit pequeno pode expandir para conteúdo grande).

**Correção:** docstring em `_file_update_size` documentando as duas semânticas. Sem mudança de comportamento.

## B5 — CRLF/UTF-8 não documentado

**Fato:** `apply_edits` casa `old_string` contra o texto UTF-8 decodificado dos bytes do arquivo, com os newlines exatos (`\r\n` incluído). Agente em Windows que normaliza newlines ao compor `old_string` recebe `EDIT_TARGET_NOT_FOUND`. Arquivo não-UTF-8 → `EDIT_INVALID`. Comportamento determinístico e fail-closed — só falta documentar.

**Correção (1 linha em cada fonte):**
- `AGENTS.md`, seção "Semântica de edits";
- `.claude/CLAUDE.md`, seção espelhada "Semântica de edits";
- `src/esaa/templates/AGENT_CONTRACT.yaml`, bloco `semantics` de `formats.edits`.

Texto: `old_string` casa contra o texto UTF-8 decodificado com os newlines exatos do arquivo (CRLF incluído — não normalizar `\r\n` para `\n`); arquivo não-UTF-8 → `EDIT_INVALID`.

## Critérios de aceitação

1. `resolve_edit_updates` standalone com item sem `content`/`edits` levanta `SCHEMA_INVALID` (não `KeyError`), com teste.
2. Docstring de `_file_update_size` presente e fiel (dual: governado = conteúdo expandido; standalone = strings dos edits).
3. As três fontes de doc trazem a linha CRLF/UTF-8 e estão consistentes entre si.
4. Suíte completa verde.

## Nota operacional

A escrita de `AGENTS.md` e `.claude/CLAUDE.md` está fora do boundary `impl` canônico; a extensão de boundary é aplicada pelo operador just-in-time na janela do submit do complete da T-2021 e revertida em seguida (o teste `test_minimal_context_changes_with_state` assert-a a lista canônica de write do contrato vivo).
