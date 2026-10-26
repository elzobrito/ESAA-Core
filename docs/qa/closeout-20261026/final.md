# Fechamento ESAA 26/10/2026 — 0.5.0b22

## Publicação

- Pacote: `esaa-core==0.5.0b22` (protocolo 0.4.2, armazenamento 0.4.1)
- PyPI: https://pypi.org/project/esaa-core/0.5.0b22/
- Git: `8013f21` (`v0.5.0b22`), PR https://github.com/elzobrito/ESAA-Core/pull/11
- CI main `40361515105` e PR `40361257193`: success (lint, test 3.11/3.12/3.13, mypy 58 arquivos)
- SHA256 wheel: `7112bb35c426b63dc91230b5a185074b3da587a94dfab004353a901354528e0a`
- SHA256 sdist: `4ab3957ba9131da853e7ac919b229756ffabded85bfaaac29a6d7d5e622e94aa`
- Token PyPI usado só como `TWINE_PASSWORD` de subprocesso; não entrou no Git nem em logs

## Instalação nesta máquina

- Python de usuário 3.14 e pipx atualizados para 0.5.0b22
- CLI: `esaa 0.5.0b22 (protocol 0.4.2, storage protocol 0.4.1, esaa 0.4.x)`
- `identity.py` instalado coincide com a fonte (`e604741af647f1793ddf38a8aadb7bc0a596238498ef4de4ed8f3108b6bb400a`)
- Core `verify` ok; home `verify` ok com aviso legado `LEGACY_SCOPE_PATCH_UNSAFE`; hash do store home inalterado
- Smoke: venv limpo e Docker `python:3.12-slim-bookworm` instalaram a b22 pública, `init`/`verify` ok, identidade inactive

## Identidade

Contrato **inactive**. Publicar e instalar não executam bootstrap nem geram chaves. Ativação continua sendo etapa do proprietário.

## Residuais abertos

- `ISSUE-ESAA-CORE-ACTOR-BOOTSTRAP-AUTHORITY-001` (provisionamento do owner)
- `ISSUE-ESAA-ACTOR-SECURITY-SCAN-STORAGE-001` (`BLOCKED_STORAGE` do scanner histórico)
- `ISS-ESAA-CLOSE-INDEPENDENT-REVIEW-20261026` (auditor automático de cibersegurança)

Não é `READY_FOR_OWNER_BOOTSTRAP`.
