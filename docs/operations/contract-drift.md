# Divergências entre contratos ativos e templates empacotados

- **Data:** 2026-11-11
- **Commit de referência:** `498eb4b` (branch `audit/onda-0`)
- **Origem:** achado DOC-03 de [docs/audit/ESAA-CORE-AUDIT-2026-11-10.md](../audit/ESAA-CORE-AUDIT-2026-11-10.md), tarefa AUD-O1-090.

## Contexto

O repositório ESAA-Core tem dois conjuntos de contratos:

- **Ativos**, em `.roadmap/`: governam este workspace.
- **Templates**, em `src/esaa/templates/`: são distribuídos no pacote e instalados em workspaces novos por `esaa bootstrap`.

O [AGENTS.md](../../AGENTS.md) estabelece que os contratos ativos "podem ter diferenças intencionais" e que não devem ser sincronizados por cópia. O teste `test_packaged_governance_templates_match_canonical_files` (`tests/test_public_beta_release.py`) fixa quais arquivos precisam ser idênticos e quais divergem de propósito: a lista `INTENTIONAL_TEMPLATE_DIVERGENCES` e o conjunto `editorial_files`.

Este documento registra o estado observado em 2026-11-11. Ele não altera nenhum contrato.

Como reproduzir a comparação:

```bash
for f in $(ls src/esaa/templates); do [ -f .roadmap/$f ] && { cmp -s .roadmap/$f src/esaa/templates/$f && echo "IGUAL $f" || echo "DIFERE $f"; }; done
```

## Arquivos idênticos

`PROJECTION_SPEC.md`, `STORAGE_POLICY.yaml`, `agents_swarm.yaml`, `issues.schema.json` e `project_profile.schema.json`.

## Arquivos divergentes

Classificação usada:

- **Intencional:** há registro da intenção no repositório (teste, changelog, commit ou documento).
- **Sem registro de intenção:** a diferença existe e o repositório não diz por quê; a decisão cabe ao operador.

| Arquivo | O que difere | Efeito prático | Classificação e evidência |
|---|---|---|---|
| `RUNTIME_POLICY.yaml` | O ativo define `resource_limit_caps` (64 atualizações, 4 MiB por atualização, 8 MiB no total). O template não define caps e traz `review_runner_separation: "off"` com comentário. | Este workspace aceita tarefas com limites acima do padrão histórico (32 / 2 MiB / 8 MiB); workspaces novos não. A chave `review_runner_separation` está ausente no ativo, o que equivale a `off`. | **Intencional** quanto aos caps: commit `aeb5312` ("Live ESAA-Core caps remain an intentional workspace divergence"), `docs/qa/core-binary-release-20261102.md` e `INTENTIONAL_TEMPLATE_DIVERGENCES`. A ausência de `review_runner_separation` no ativo decorre de a chave ter sido criada depois (AUD-O0-020) e não muda o comportamento. |
| `ORCHESTRATOR_CONTRACT.yaml` | O template lista as ações `verification.configure` e `verification.run`; o ativo não. | Documental neste workspace: a extensão de verificação executável é opcional e não está habilitada aqui. | **Intencional:** `INTENTIONAL_TEMPLATE_DIVERGENCES` com esses dois marcadores. |
| `agent_result.schema.json` | O template aceita `execution_id` dentro de `verification` e o campo `review_mode` no evento; o ativo não. | Neste workspace, um envelope de agente com `review_mode` ou `verification.execution_id` é rejeitado pelo schema. | **Intencional:** `INTENTIONAL_TEMPLATE_DIVERGENCES` (marcador `review_mode`). O efeito sobre `execution_id` não tem registro próprio. |
| `roadmap.schema.json` | O template aceita nas tarefas `task_type`, `acceptance_criteria`, `required_review_mode`, `supersedes`, `superseded_by`, `executable_checks` e `execution_id`; o ativo não. | `esaa task create` valida a projeção contra o schema ativo. Neste workspace, usar `--task-type`, `--acceptance-criterion`, `--required-review-mode` ou `--supersedes` falha com `SCHEMA_INVALID` ("Additional properties are not allowed"), embora a CLI ofereça as opções. Observado ao registrar as tarefas AUD-O0 e AUD-O1, cujos critérios de aceite foram para a descrição. | **Intencional** quanto à diferença: `INTENTIONAL_TEMPLATE_DIVERGENCES` (marcadores `task_type`, `acceptance_criteria`, `required_review_mode`). **Sem registro de intenção** quanto ao efeito de bloquear essas opções da CLI neste workspace — decisão pendente do operador. |
| `lessons.schema.json` | O ativo aceita só os status `active` e `archived`; o template acrescenta `proposed`, `experimental` e `superseded`, os escopos `task_types`, `review_modes`, `paths`, `actors` e `runners`, e os modos `require_check`, `require_note`, `require_review_mode` e `require_boundary_grant`. | O schema de lessons não é validado em runtime, então nada é rejeitado hoje. Uma lesson `proposed` (AUD-O0-030) gravada em `.roadmap/lessons.json` não estaria conforme o schema ativo se alguém validasse o arquivo. | **Intencional** quanto à diferença: `INTENTIONAL_TEMPLATE_DIVERGENCES` (marcadores `experimental`, `require_boundary_grant`). **Sem registro de intenção** quanto ao status `proposed` — decisão pendente do operador. |
| `AGENT_CONTRACT.yaml` | O template lista `verification.configure` e `verification.run` entre as ações reservadas e descreve claim e complete como submissões distintas com revisão e novas tentativas; o ativo diz que o Orchestrator invoca o agente "exatamente duas vezes por tarefa". | O texto ativo descreve o ciclo de forma mais restrita do que a máquina de estados permite (`request_changes` leva a novas submissões). Os boundaries, que são a parte aplicada pelo validador, são iguais. | **Intencional (editorial):** o arquivo está em `editorial_files` do mesmo teste; o changelog 0.5.0b19 registra a reescrita dos guias empacotados. |
| `PARCER_PROFILE.agent-docs.yaml`, `agent-impl`, `agent-qa`, `agent-spec`, `orchestrator-runtime` | Os templates são versões condensadas (por exemplo, `agent-impl`: 62 linhas no template, 18 KB no ativo). | Orientação por papel, carregada sob demanda; não é aplicada pelo runtime. Agentes deste workspace leem a versão longa. | **Intencional (editorial):** `editorial_files`; `docs/spec/GUIDE-20260905.md` e `docs/qa/GUIDE-20260905.md` registram a condensação dos cinco perfis. |

## Arquivos presentes em um lado só

- **Só no template:** `esaa-plugin.schema.json` (schema de manifesto de plugin; não é instalado em `.roadmap/`).
- **Só no ativo:** `init.yaml`, `activity_future_templates.jsonl` e `runner-inputs/`, além do event store, das projeções e dos diretórios de runtime (`artifacts/`, `backups/`, `staging/`). Não foi encontrada leitura de `init.yaml` nem de `activity_future_templates.jsonl` pelo runtime — sem registro de intenção sobre mantê-los versionados.

## Observações

- **Template em alteração:** a tarefa AUD-O1-080 (validação da política) pode alterar `src/esaa/templates/RUNTIME_POLICY.yaml` em paralelo a este registro. A tabela descreve o commit `498eb4b`.
- **Cobertura do teste:** o teste de paridade confere que os arquivos da lista intencional diferem e que os marcadores existem no template. Ele não descreve o efeito de cada diferença nem acusa diferenças novas dentro de um arquivo já listado.
- **Caminho de migração existente:** `esaa contract migrate` atualiza seletivamente `agent_result.schema.json` e `roadmap.schema.json` ativos (efeitos binários e `resource_limits`), com backup em `.roadmap/backups/contracts/` e `esaa contract revert --from <backup>`. Ele não cobre os campos G07 de `roadmap.schema.json` nem `lessons.schema.json`. Não foi executado para este registro.

## Decisões pendentes do operador

1. Manter ou não o `roadmap.schema.json` ativo sem os campos G07, dado que isso bloqueia opções de `task create` neste workspace.
2. Aceitar ou não o status `proposed` no `lessons.schema.json` ativo.
3. Manter ou não `init.yaml` e `activity_future_templates.jsonl` versionados.
