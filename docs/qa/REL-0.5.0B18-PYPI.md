# REL-0.5.0B18-PYPI — Publicação no PyPI

## Pacote

- Nome: `esaa-core`
- Versão: **0.5.0b18**
- Artefatos locais:
  - `dist/esaa_core-0.5.0b18-py3-none-any.whl`
  - `dist/esaa_core-0.5.0b18.tar.gz`

## Gates anteriores ao upload

- Testes de versão, release e assets: **33 passed**.
- Suíte completa: **398 passed**, com uma única falha histórica fora do
  escopo em `test_done_tasks_have_governed_evidence` para
  `HF-ISS-COD-ALARM-STATE-MACHINE-SEPARATION` sem `issue.resolve`.
- `python -m twine check`: **PASSED** para wheel e sdist.
- Inventário do wheel idêntico aos módulos e package-data esperados.
- Wheel instalado em venv limpa; `bootstrap`, `init` e `verify` aprovados.
- `bootstrap --force` preservou os hashes de `activity.jsonl`, `roadmap.json`,
  `issues.json` e `lessons.json`.

## Upload

Ferramenta: `twine` 6.x → `https://upload.pypi.org/legacy/`

```text
Uploading esaa_core-0.5.0b18-py3-none-any.whl
Uploading esaa_core-0.5.0b18.tar.gz

View at:
https://pypi.org/project/esaa-core/0.5.0b18/
```

## Verificação pública

URL: https://pypi.org/project/esaa-core/0.5.0b18/

```json
{
  "version": "0.5.0b18",
  "files": [
    {
      "filename": "esaa_core-0.5.0b18-py3-none-any.whl",
      "sha256": "bf0597574e7eaa8bb6b323a17461e319de3f4b154e3b5e1d632bf11f186245da",
      "yanked": false
    },
    {
      "filename": "esaa_core-0.5.0b18.tar.gz",
      "sha256": "1b5023583e8e91b9dd0b5d2fda745f5bfc34f98e137be1c23e5e9a18bf2e78cc",
      "yanked": false
    }
  ]
}
```

Uma instalação pública, sem cache e usando `https://pypi.org/simple`, retornou
`esaa 0.5.0b18`; o bootstrap gerado correspondeu aos guias canônicos e
`verify_status` retornou `ok`.

## Segurança

- Token lido do arquivo local indicado pelo operador, fora do repositório.
- Token não foi impresso, commitado ou embutido neste relatório.
- Autenticação: `TWINE_USERNAME=__token__` e senha fornecida ao processo por
  variável de ambiente.

## Conclusão

**PASS** — `esaa-core 0.5.0b18` publicado no PyPI com wheel e sdist completos.
