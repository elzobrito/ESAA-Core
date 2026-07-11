# REL-0.5.0B17-PYPI — Publicação no PyPI

## Pacote

- Nome: `esaa-core`
- Versão: **0.5.0b17**
- Artefatos locais:
  - `dist/esaa_core-0.5.0b17-py3-none-any.whl`
  - `dist/esaa_core-0.5.0b17.tar.gz`

## Upload

Ferramenta: `twine` 6.x → `https://upload.pypi.org/legacy/`

Saída (token redigido):

```text
Uploading distributions to https://upload.pypi.org/legacy/
Uploading esaa_core-0.5.0b17-py3-none-any.whl

Uploading esaa_core-0.5.0b17.tar.gz


View at:
https://pypi.org/project/esaa-core/0.5.0b17/
```

## Verificação pública

URL: https://pypi.org/project/esaa-core/0.5.0b17/

```json
{
  "version": "0.5.0b17",
  "files": [
    "esaa_core-0.5.0b17-py3-none-any.whl",
    "esaa_core-0.5.0b17.tar.gz"
  ],
  "yanked": false
}
```

## Segurança

- Token lido de arquivo local do operador (fora do repositório).
- Token **não** commitado e **não** embutido neste relatório.
- Autenticação: `TWINE_USERNAME=__token__` + senha via variável de ambiente na sessão de upload.

## Conclusão

**PASS** — `esaa-core 0.5.0b17` publicado no PyPI com wheel e sdist.
