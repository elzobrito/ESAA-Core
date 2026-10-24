# Validação das correções ESAA levantadas pelo Grok

Data: 24/10/2026. Workspace: `/home/elzobrito/desenvolvimento/ESAA-Core`.

O plano foi implementado no código do ESAA-Core com tarefas autossuficientes, claim, entrega por `file_updates`, revisão e verificação. Os resultados reproduzíveis estão em [results.json](results.json), com hashes dos pacotes em [SHA256SUMS](SHA256SUMS). O [guia Grok/Antigravity](../../guides/esaa-grok-antigravity.md) explica o protocolo e o fluxo operacional completo; existe também uma versão em inglês.

## Lacunas e entregas

| Lacuna | Correção e limite |
| --- | --- |
| Hotfix bloqueia arquivo na raiz | `hotfix create --boundary-grant` concede caminhos explicitamente; `--scope-patch` restringe escopo e não concede escrita. Outputs e grants podem ser corrigidos em tarefa `todo`. Grants não são herdados automaticamente. |
| Exemplo cria hotfix duplicado | Cenário 9 PT/EN corrigido: reportar issue sem `--fixes` quando o hotfix será criado explicitamente. Mensagem de duplicação informa o identificador existente e recuperação. |
| Verify domina o log | `activity list --hide-verify` e filtros permitem leitura útil sem eliminar os eventos de auditoria. Não foi prometida redução de 60% nem alterada a política de registro. |
| Checks apenas declarados | Verificação executável opcional, ativada por operador com catálogo explícito. `verification run` executa em Docker e `complete` exige resultado válido vinculado ao candidato. Checks declarativos legados continuam disponíveis. |
| CLI não lista todas as tarefas | `task list` inclui tarefas persistidas e planejadas, filtros e paginação com rejeição de cursor desatualizado. Consultas não inicializam store inexistente nem escrevem eventos. |

A verificação executável associa tarefa, actor, ciclo, configuração, arquivos de entrada e conteúdo candidato. O gate verifica a evidência novamente sob lock antes dos efeitos finais e rejeita resultados ausentes, falhos, adulterados ou desatualizados. `complete`, replay, dry-run e `verify` não executam testes implicitamente.

O executor usa imagem local fixada por digest, sem download automático, rede ou mount do workspace. A cópia limitada entra por TAR em tmpfs privado; o processo usa usuário sem privilégios, filesystem raiz somente leitura, capabilities removidas e limites de CPU, memória, PIDs, tempo, tamanho e logs. A imagem precisa fornecer `/bin/sh` e `tar`. Docker é obrigatório para esse recurso: não há fallback de execução local. O conteúdo executável do catálogo permanece uma escolha explícita do operador.

## Evidências observadas

- Baseline anterior: **477 testes passaram em 42,26 s**.
- Suíte final: **531 testes passaram em 48,69 s**, com `ESAA_TEST_DOCKER=1`. Comando completo em `results.json`.
- Docker real: execução bem-sucedida, isolamento, saída não zero, timeout, truncamento dos logs e remoção dos containers; indisponibilidade e cancelamento também têm testes específicos.
- Wheel e sdist construídos e instalados em dois venvs limpos, fora do checkout e sem `PYTHONPATH`. Ambos importaram o pacote de seus próprios `site-packages` e passaram pelo ciclo tarefa → Docker → complete → review → done, seguido de issue → hotfix com grant para arquivo na raiz → dois checks → done e issue resolvida.
- Cada instalação executou três checks reais; os controles negativos retornaram `VERIFICATION_REQUIRED` e `VERIFICATION_STALE`. Consultas preservaram o store; `verify` e `verify --chain` retornaram `ok` nos dois workspaces sintéticos, seq 48.
- Exemplo executável dos guias PT/EN validado em workspace descartável. Links locais e equivalência dos blocos PT/EN conferidos.
- Ruff check e format passaram nos módulos novos e respectivos testes; orçamento dos módulos existentes preservado.
- Comparação de **181 arquivos** confirmou paridade entre candidato testado e fonte entregue, excluindo metadados gerados e caches. Oito arquivos associados ao trabalho preexistente de identidade, registro e replay assinado permaneceram idênticos ao snapshot anterior; a suíte inclui sua regressão.
- Revisões independentes acompanharam os escopos de implementação e os três hotfixes. A revisão final da tarefa QA usa estes artefatos antes do encerramento governado.

Os primeiros testes de distribuição revelaram projeção desatualizada logo após `chain init`. O problema foi reproduzido, registrado como issue e corrigido por hotfix: cálculo da âncora sob lock e projeção na mesma transação. As instalações foram reconstruídas e repetidas com sucesso. Outros dois hotfixes preservaram scopes `runtime://` legados e a posição de `dry_run` na API Python; novos parâmetros são keyword-only. As falhas intermediárias não foram usadas como evidência de aprovação.

## Rastreabilidade e reprodução

As tarefas `ESAA-GROK-20261024-001` a `009` cobrem baseline, grants, consultas, configuração, executor, gate, guias, QA e normalização. Os hotfixes são `HF-ISS-ESAA-GROK-LEGACY-SCOPE`, `HF-ISS-ESAA-GROK-CHAIN-PROJECTION` e `HF-ISS-ESAA-GROK-POSITIONAL`. O event store do workspace é a fonte do estado final e das decisões; este relatório não substitui sua consulta.

Para reproduzir a distribuição, construir com `python -m build`, instalar cada artefato em um venv separado e executar [distribution_smoke.py](distribution_smoke.py) usando o Python instalado, fora do checkout, com `PYTHONPATH` removido:

```bash
env -u PYTHONPATH /caminho/venv/bin/python /caminho/distribution_smoke.py   --label wheel --summary /tmp/esaa-wheel-smoke.json
```

O script requer Docker e o digest Alpine explícito no código disponível localmente; cria somente workspaces descartáveis. Logs brutos, cópia candidata e pacotes desta execução estão em `/tmp/esaa-grok-ng2vtrjq`; os resumos e hashes duráveis estão neste diretório do repositório. Artefatos em `/tmp` podem ser limpos pelo sistema.

## Compatibilidade e fronteiras da validação

O número do pacote permanece **0.5.0b19**: esta entrega é um candidato local, sem release, publicação ou instalação global. O protocolo opcional anunciado pelo fonte é **0.4.2**, mantendo o schema base **0.4.1**; eventos e assinaturas históricos são preservados. Ativar a extensão requer consumidores capazes de ler os novos eventos: não voltar a um leitor antigo sobre um store já ativado.

Nenhum arquivo do Tetris original foi alterado nem sua interface gráfica foi executada. Os exemplos usam uma fixture textual sintética chamada `tetris.py`; comprovam o protocolo e a distribuição, sem alegar aceitação visual, segurança de produção ou validação do jogo. Alterações preexistentes e backlog de outros trabalhos foram preservados. Não houve commit, push nem publicação.
