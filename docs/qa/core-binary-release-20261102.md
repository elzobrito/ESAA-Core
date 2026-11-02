# ESAA-Core 0.5.0b25 — evidência de publicação (efeitos binários)

Data: 2026-11-02. Status: publicado no Git e no PyPI. Sem GitHub Release.

Versão recomendada para instalação: **esaa-core==0.5.0b25**.

## Tarefas

- `CORE-BINARY-FILE-EFFECTS-20261102` done (seq 1688, 40 file_updates, actor agent-impl, review agent-qa).
- `CORE-BINARY-RELEASE-20261102` claimed by agent-impl (seq 1691). Complete não é publicação; Git/PyPI/install ocorreram nesta tarefa.

## Fonte Git

- Remote: https://github.com/elzobrito/ESAA-Core.git
- Branch `main`: `aeb53120f7599127238293ae75302f808d3e5d31`
- Tag anotada: `v0.5.0b25` (objeto aponta para o mesmo commit)
- Commits desta entrega:
  - `dbf4016317b1c36ace843de4b582a6d2e3ff6917` — 0.5.0b23 feature (binary file_updates, limits, contract migrate)
  - `c6db991099926ffdceb5c39ff712110796a5ef92` — 0.5.0b24 tentativa de alinhar template (superesedida)
  - `aeb53120f7599127238293ae75302f808d3e5d31` — 0.5.0b25 template histórico + divergência intencional de RUNTIME_POLICY
- GitHub Release: não criado (evita `python-publish.yml` / trusted publishing). Apenas git tag.

## PyPI

- URL: https://pypi.org/project/esaa-core/0.5.0b25/
- Twine check: PASSED (wheel e sdist)
- SHA-256 local = SHA-256 PyPI

| Artefato | SHA-256 | bytes |
|---|---|---|
| `esaa_core-0.5.0b25-py3-none-any.whl` | `cc6444404e0a3600b5e8c4262ee3f977978fafd1f4f29de6a303cfdbcc0cede8` | 178847 |
| `esaa_core-0.5.0b25.tar.gz` | `60749e0c7f2e7d36364598525290cd9cae0a03a1dbdfe79eb45bb9a4e2a20a91` | 420017 |

Token: lido de arquivo local via `TWINE_PASSWORD` em subprocesso; nunca impresso, copiado ou commitado.

## Versões intermediárias (não instalar)

- **0.5.0b23** (`dbf4016`, CI 41486002227 failure): `.roadmap/RUNTIME_POLICY.yaml` ganhou `resource_limit_caps` e o template empacotado não; `test_packaged_governance_templates_match_canonical_files` falhou. PyPI: https://pypi.org/project/esaa-core/0.5.0b23/
- **0.5.0b24** (`c6db991`, CI 41486508999 failure): template passou a incluir caps; `test_policy_changed_between_validation_and_commit_is_rejected` deixou de rejeitar porque o teto administrativo ficou 4MiB. PyPI: https://pypi.org/project/esaa-core/0.5.0b24/

Correção em b25: template empacotado permanece sem caps (teto histórico 32 / 2MiB / 8MiB). Caps do workspace ESAA-Core são divergência intencional (`INTENTIONAL_TEMPLATE_DIVERGENCES` inclui `RUNTIME_POLICY.yaml`).

## CI

- Run: https://github.com/elzobrito/ESAA-Core/actions/runs/41486999420
- Event: push `main` `aeb5312`
- conclusion: **success**
- lint: success
- test 3.11 / 3.12 / 3.13: success
- typecheck: failure (job `continue-on-error`, advisory desde QUA-01; não bloqueia)

Pytest local no FILE-EFFECTS: 652 passed, 4 skipped.

## Instalação nesta máquina

Comando user-pip:

```bash
/usr/bin/python3 -m pip install --user --break-system-packages --pre --upgrade esaa-core==0.5.0b25
```

- Python: 3.14.4
- PATH `esaa`: `/home/elzobrito/.local/bin/esaa`
- Módulo: `/home/elzobrito/.local/lib/python3.14/site-packages/esaa/__init__.py`
- `esaa --version`: `esaa 0.5.0b25 (protocol 0.4.2, storage protocol 0.4.1, esaa 0.4.x)`
- pipx: `esaa-core` 0.5.0b25 (venv em `~/.local/share/pipx/venvs/esaa-core`; o binário PATH continua o user-pip)

Smoke venv limpo (`/tmp/esaa-b24-install-venv` para b24; b25 instalado no user-pip): bootstrap public + init + verify em workspace temporário → `verify_status=ok`, seq 4, hash `411885afdc5e0e74e1eac70f8cef0094ef6842c1b5c11b34654bb1e3b0664d50`. CLI instalada oferece `esaa contract migrate` e `esaa task set-limits`.

ESAA-Core `verify` com CLI instalada (PYTHONPATH unset): ok, seq 1691, hash `07f209649acea71a1940730a970753ca5794a3c1edbbc31ae340dcda5099e686` (antes deste complete).

## Contrato e limites no workspace vivo

- `esaa contract migrate` (não `bootstrap --force`): `.roadmap/agent_result.schema.json` `683560ed…`, `.roadmap/roadmap.schema.json` `35d1e3fa…`; backup `.roadmap/backups/contracts/20261102T164858Z`.
- `resource_limit_caps` no `.roadmap/RUNTIME_POLICY.yaml` do ESAA-Core: 64 / 4MiB / 8MiB.
- `task.limits.set` em FILE-EFFECTS: `max_file_updates=64`, authorized-by operator.

## Identidade e resíduos

- identity_contract: inactive. Sem bootstrap, sem mint de chaves, sem `--force`.
- ISS-PTB-BINARY-EFFECTS-20261102 permanece aberta até prova no workspace PTB.
- Sem GitHub Release para b23/b24/b25.

## Próximo passo

Instalar `esaa-core==0.5.0b25` no workspace PTB, migrar contratos, declarar limites da ML02 e retomar PNG/FFV1 pelos efeitos do Orchestrator.
