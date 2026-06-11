# G05 — Especificação: Sandbox de External Effects e Limites de Recursos

> Tarefa: T-014 (spec) · Targets: SEC-05, SEC-06 · Depende: T-002
> Motivação: `_target_root` aceita caminho absoluto arbitrário vindo do INPUT
> do plugin; com `allowed_write` permissivo, um input malicioso escreve em
> qualquer diretório do sistema. Não há limites de volume em `file_updates`
> nem na resposta de adapters HTTP.

## SEC-05 — Allowlist de target roots

1. **RUNTIME_POLICY ganha**:
   ```yaml
   external_effects:
     allowed_roots: []        # vazio = NENHUM external effect permitido
     allow_glob_wildcard: false
   ```
   `allowed_roots` lista prefixos absolutos (ou relativos ao workspace)
   autorizados. `_target_root` resolve o root do input e exige
   `resolved.is_relative_to(allowed)` para algum item — senão
   `EXTERNAL_ROOT_NOT_ALLOWED` (fail-closed; default vazio = negado).
2. **Globs perigosos**: `allowed_write` contendo `**` sem prefixo de
   diretório (`**`, `**/*`) é rejeitado no `plugin doctor` E no submit
   (`PLUGIN_SCHEMA_INVALID`) salvo `allow_glob_wildcard: true` explícito.
3. **Dry-run primeiro-uso**: primeira escrita externa de um par
   (plugin, target) numa run exige que o submit anterior tenha sido dry-run
   OU que a policy declare `external_effects.require_dry_run: false`.
   Default: true (operador vê os caminhos resolvidos antes do efeito real).
4. Traversal/absolute em `target_path` continuam bloqueados (regressão).

## SEC-06 — Limites de recursos

1. **RUNTIME_POLICY ganha**:
   ```yaml
   resource_limits:
     max_file_updates: 32          # por submit
     max_bytes_per_update: 2097152 # 2 MiB
     max_bytes_total: 8388608      # 8 MiB por submit
     max_adapter_response_bytes: 4194304  # 4 MiB
   ```
2. Validação ANTES de staging (validator/service): excedeu →
   `RESOURCE_LIMIT_EXCEEDED` com detalhe de qual limite; staging nem inicia,
   zero efeitos parciais.
3. `HttpLlmAdapter.execute` lê a resposta com teto de bytes (stream com
   limite); exceder → `RESOURCE_LIMIT_EXCEEDED` sem carregar o corpo inteiro
   em memória.
4. Limites são por-workspace (policy), com mínimos sanos validados no load
   (ex.: max_file_updates >= 1) para impedir auto-bloqueio acidental.

## Interações

- G08: eventos de rejeição por limite carregam `runner` — abuso é atribuível.
- G02: efeitos externos ficam fora do workspace e, portanto, fora do recovery
  por artifacts? NÃO — artifacts content-addressed continuam sendo gravados
  no workspace (já é assim); a allowlist só restringe o destino final.
- Acordo híbrido: mudanças em RUNTIME_POLICY.yaml são do operador.

## Critérios de aceite

1. Input de plugin com root fora de `allowed_roots` → `EXTERNAL_ROOT_NOT_ALLOWED`,
   mesmo com allowed_write válido; default (lista vazia) nega tudo.
2. `allowed_write: ["**"]` rejeitado no doctor e no submit (sem opt-in).
3. `file_updates` acima de qualquer limite → `RESOURCE_LIMIT_EXCEEDED`,
   staging vazio (verificado em disco), evento nenhum persistido.
4. Resposta de adapter acima do teto → rejeição sem pico de memória
   proporcional ao corpo.
5. Testes de regressão de traversal/absolute permanecem verdes.

## Novos códigos

`EXTERNAL_ROOT_NOT_ALLOWED`, `RESOURCE_LIMIT_EXCEEDED` — registrados em
`reject_codes.py` (M-04).
