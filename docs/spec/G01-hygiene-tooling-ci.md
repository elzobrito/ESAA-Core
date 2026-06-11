# G01 — Especificação: Higiene, Tooling e CI

> Tarefa: T-001 (spec) · Targets: QUA-01..QUA-06 · Roadmap: correction-plan
> Execução híbrida acordada: itens fora do boundary `impl` (pyproject.toml,
> .gitignore, .github/**, tools/**, examples/**) são aplicados pelo operador,
> com rastreabilidade nas notes do evento `complete` de T-002.

## QUA-01 — Formatação e mojibake

Problema: `src/esaa/file_effects.py` contém comentários com encoding corrompido
(em dash UTF-8 duplamente codificado), CRLF e linhas em branco duplicadas;
`src/esaa/service.py` tem seções com espaçamento duplo gerado automaticamente.

Especificação:
1. Normalizar `file_effects.py` e `service.py`: UTF-8 limpo, LF, no máximo
   1 linha em branco dentro de funções e 2 entre definições de topo.
2. Zero mudança de comportamento: a suíte completa deve passar inalterada.
3. Adoção de ruff (lint) e black (formato) configurados no `pyproject.toml`,
   aplicados primeiro aos arquivos tocados; o restante do repositório adere
   gradualmente com gate de CI para novos arquivos.
4. mypy adicionado em modo pragmático (non-strict) como job não-bloqueante
   inicialmente; promoção a bloqueante em fase posterior.

Aceite: nenhum byte de mojibake na árvore `src/`; `ruff check` e
`black --check` verdes nos arquivos do escopo; suíte verde.

## QUA-02 — Fonte única de versão

Problema: versão declarada em três lugares (pyproject `0.5.0b5`,
`constants.PACKAGE_VERSION`, dist `0.5.0b4`) com drift real.

Especificação: `src/esaa/constants.py::PACKAGE_VERSION` torna-se a fonte
única. O `pyproject.toml` passa a usar `dynamic = ["version"]` com
`[tool.setuptools.dynamic] version = {attr = "esaa.constants.PACKAGE_VERSION"}`.
Documentar que a versão de CONTRATO (0.4.1 em `.roadmap/`) é deliberadamente
distinta da versão de PACOTE — não devem ser sincronizadas entre si.

Aceite: `python -m esaa --version`, `importlib.metadata` (quando instalado)
e o build wheel reportam o mesmo valor; teste automatizado compara
`constants.PACKAGE_VERSION` ao `pyproject.toml`.

## QUA-03 — .gitignore e higiene da árvore

Problema: padrão com typo (`./roadmap/artifacts/` não corresponde a
`.roadmap/artifacts/`), `dist/` não ignorado, `__pycache__`/`.pyc` presentes.

Especificação: corrigir os padrões para `.roadmap/artifacts/`,
adicionar `dist/`; remover bytecode da árvore; `test_repository_hygiene`
amplia cobertura para esses casos e para detecção de mojibake.

Aceite: testes de higiene falham em regressão de qualquer item acima.

## QUA-04 — Assets de cliente fora do framework

Problema: `sso-config.sql`, `roadmap.sso-client-all-in-one.template.json`,
`SsoAllIn-portugues-estruturado.md` e `sso-client-input.local.example.json`
são artefatos de um cliente específico dentro de `.roadmap/` do framework.

Especificação: mover para `examples/plugins/sso-client/` preservando
conteúdo; nenhum código referencia esses caminhos (verificado por grep
em src/tests/docs). `.roadmap/` passa a conter apenas artefatos de
governança do próprio framework.

Aceite: arquivos ausentes de `.roadmap/`, presentes em
`examples/plugins/sso-client/`, suíte verde.

## QUA-05 — Scripts de auditoria fora do pacote

Problema: `src/audit/` contém scripts one-off de manutenção dentro da
árvore de pacote distribuível.

Especificação: mover para `tools/audit/`; atualizar os 3 módulos de teste
que importam `src.audit.*` para `tools.audit.*` (imports por namespace
package, sem necessidade de `__init__.py`).

Aceite: `pip wheel` não empacota módulo audit; suíte verde com novos imports.

## QUA-06 — CI

Especificação: `.github/workflows/ci.yml` com jobs: (a) lint — ruff +
black --check no escopo adotado; (b) testes — pytest em matriz Python
3.11/3.12/3.13; (c) mypy não-bloqueante. Gate obrigatório para merge.
`requires-python >=3.11` permanece (uso de `tomllib` em testes).

Aceite: pipeline executa nos 3 interpretadores; falha de lint ou teste
bloqueia o merge.

## Fora de escopo de G01

Hash chain, identidade de actors, locks, external effects, decomposição do
service e performance — ver G02..G07 no roadmap de correção.
