# Release 0.5.0b20 — fechamento da instalação

- **0.5.0b20** foi publicada (ver `publish.json`), mas **não foi instalada** nesta máquina: `esaa verify` no workspace home falhava com `HOTFIX_SCOPE_INVALID` por causa de um `scope_patch` absoluto legado.
- Corrigido por `ISS-ESAA-B21-LEGACY-ABS-SCOPE` → `HF-ISS-ESAA-B21-LEGACY-ABS-SCOPE` (replay aceita escopo legado; comandos novos continuam rejeitando; `verify` emite aviso `LEGACY_SCOPE_PATCH_UNSAFE`).
- Instalada **0.5.0b21** do PyPI (`--user`) no notebook e na box; `esaa --version` = `0.5.0b21 (protocol 0.4.2, storage protocol 0.4.1)`.
- `esaa verify` em `~`: ok (8168 eventos, ~/.roadmap inalterado) com 1 aviso legado; em ESAA-Core: ok.
- Commit `a53b27a`, tag `v0.5.0b21`, CI run 40101278716 success. Sem GitHub release. Token nunca exibido.
