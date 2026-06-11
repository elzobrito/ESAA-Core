# G05 - Dissolucao do service_common e higiene de formatacao (M3, B4)

## Problema

A decomposicao de `src/esaa/service.py` reduziu o monolito, mas preservou o comportamento por meio de um barril interno:

```python
from .service_common import *
# ruff: noqa: F403,F405
```

Esse padrao aparece nos modulos centrais do single writer (`service.py`, `service_core.py`, `submission.py`, `execution.py`, `task_admin.py`, `seeds.py`, `events.py`). Ele foi aceitavel como etapa mecanica de extracao, mas deve ser removido antes de considerar a arquitetura estabilizada, porque:

1. Desliga a deteccao estatica de nomes indefinidos (`F403/F405`) no nucleo do Orchestrator.
2. Esconde as dependencias reais de cada modulo.
3. Torna refactors futuros mais arriscados: remover um import do barril pode quebrar qualquer modulo consumidor.
4. Mantem linhas em branco duplicadas em corpos de funcao, artefato da extracao mecanica (B4), dificultando revisao.

## Semantica alvo

1. `src/esaa/service_common.py` deve ser removido sem shim.
2. Cada modulo deve importar explicitamente apenas os simbolos que usa.
3. Nenhum modulo em `src/esaa/` deve usar `from .service_common import *`.
4. Nenhum modulo em `src/esaa/` deve manter `# ruff: noqa: F403,F405` para mascarar imports indefinidos.
5. A limpeza de formatacao deve ser limitada a remover blank lines duplicadas em corpos de funcao e deixar `black` estabilizar o resultado; nao misturar refactor comportamental.

## Ordem de execucao recomendada

Executar modulo por modulo, com teste curto entre etapas quando necessario:

1. `events.py`: importar `Any`, `json`, `SCHEMA_VERSION`, `materialize`, `next_event_seq`, `resolve_runner`, `ESAAError`, `utc_now_iso`.
2. `seeds.py`: importar `Any`, `Path`, `json`, `load_active_roadmap_tasks`, `normalize_write_set`, `conflict_between_sets`, `expected_action_for`, `allowed_actions_for`, `build_minimal_context`.
3. `service_core.py`: importar `Any`, `Path`, `json`, `random`, `time`, `Draft202012Validator`, `FormatChecker`, adapters, store/projector/file_effects/runtime_policy/metrics/runner_metrics conforme uso local.
4. `submission.py`: importar `Any`, `Path`, `json`, validators, store/projector/runtime_policy/provenance/file_effects/external_effects/conflicts/utils conforme uso local.
5. `execution.py`: importar `Any`, `datetime`, `timezone`, `ThreadPoolExecutor`, store/projector/runtime_policy/file_effects e helpers locais.
6. `task_admin.py`: importar `Any`, `Path`, `datetime`, `timezone`, store/projector/state_machine/errors/utils e helpers de events/seeds.
7. `service.py`: manter facade com imports explicitos e `__all__`, sem importar o barril.

Depois de cada modulo, rodar pelo menos:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_service_decomposition.py -q
python -m ruff check --select F821 src/esaa/<modulo>.py
```

## Tabela de lookup para imports

Usar `src/esaa/service_common.py` atual apenas como inventario temporario:

- stdlib: `json`, `random`, `time`, `ThreadPoolExecutor`, `datetime`, `timezone`, `Path`, `Any`.
- terceiro: `jsonschema.Draft202012Validator`, `jsonschema.FormatChecker`.
- internos: `adapters`, `conflicts`, `constants`, `dispatch`, `edits`, `errors`, `external_effects`, `file_effects`, `metrics`, `plugins`, `projector`, `provenance`, `runner_metrics`, `runtime_policy`, `state_machine`, `store`, `utils`, `validator`.

Essa tabela nao deve permanecer como modulo importavel ao final.

## Invariantes comportamentais

1. `ESAAService` continua importavel por `from esaa.service import ESAAService`.
2. Reexports publicos de `service.py` continuam disponiveis: `make_event`, `dumps_pretty`, `validate_hotfix_request`, `build_hotfix_event`, `build_issue_resolve_event`, `BASELINE_LESSONS`, `seed_tasks`, `load_plugin_seeds`, `find_planned_plugin_task`, `tasks_with_planned_plugins`, `load_audit_seed`, `all_tasks_done`, `select_next_task`, `select_task_wave`, `list_eligible_tasks`, `parallel_groups`, `build_dispatch_context`.
3. `tests/test_service_decomposition.py` permanece verde e todos os modulos principais seguem com no maximo 500 linhas.
4. `tools/audit/critical_findings.py` continua encontrando os markers nos modulos varridos: `BASELINE_LESSONS`, `baseline_reseed`, `validate_hotfix_request`, `tasks_with_planned_plugins`, `_accept_agent_output`, `task.create`, `would_append_events`, `simulated_last_event_seq`.
5. Nenhuma mudanca de workflow ESAA e introduzida nesta task; o objetivo e hygiene/imports.

## Criterios de aceitacao

1. `src/esaa/service_common.py` removido.
2. `rg "service_common" src tests` sem resultados.
3. `rg "noqa: F403|noqa: F405" src/esaa` sem resultados.
4. `python -m ruff check --select F821 src/esaa` sem erros.
5. `python -m ruff check src tools tests` sem novos erros relacionados a F403/F405/F821.
6. `python -m black --check src/esaa tools/audit` verde.
7. `PYTHONPATH=src python -m pytest -q` verde.
8. `PYTHONPATH=src python tools/audit/critical_findings.py --root .` retorna `total_findings: 0` e exit code 0.
9. Smoke import verde:

```powershell
$env:PYTHONPATH='src'; python -c "import esaa.service as s; assert s.ESAAService"
```

## Risco e mitigacao

O risco principal e quebrar imports em caminhos menos exercitados. A mitigacao e executar a remocao incrementalmente, rodar `ruff --select F821` por modulo, manter a suite completa como gate final e evitar qualquer mudanca de comportamento no mesmo patch.

A implementacao G05 deve entrar por ultimo no roadmap porque depende do churn de `T-2011` e `T-2021` nos mesmos arquivos centrais. Isso reduz retrabalho e evita resolver conflitos de import duas vezes.
