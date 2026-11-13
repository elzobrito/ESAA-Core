---
titulo: "ADR 0007 — Plugins e roadmaps projetados a partir do log"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0007 — Plugins e roadmaps projetados a partir do log

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Proposto — implementação exclusiva da AUD-O2-060, após AUD-O2-050.

## Contexto

Hoje [src/esaa/plugins.py:535 — `install_plugin`](../../src/esaa/plugins.py#L535), [src/esaa/plugins.py:554 — `remove_plugin`](../../src/esaa/plugins.py#L554), [src/esaa/plugins.py:599 — `activate_roadmap`](../../src/esaa/plugins.py#L599), [src/esaa/plugins.py:651 — `set_roadmap_status`](../../src/esaa/plugins.py#L651) e [src/esaa/plugins.py:663 — `deactivate_roadmap`](../../src/esaa/plugins.py#L663) escrevem locks diretamente. Os ramos `plugin.*`/`roadmap.*` em [src/esaa/projector.py:394 — `_apply_event`](../../src/esaa/projector.py#L394) são no-op. Esse estado não é reconstruído a partir do histórico.

## Decisão

1. Tornar `plugin.install`, `plugin.update`, `plugin.remove`, `roadmap.activate`, `roadmap.pause`, `roadmap.resume`, `roadmap.deactivate` e `contract.set` ações canônicas reservadas ao Orchestrator, com payloads validados no append pelo mecanismo de [adr-0008](0008-schema-append-upcasters.md). Usar o caminho de commit do Orchestrator, lock único do store, releitura e runner carimbado; dry-run não escreve evento, locks nem cópias de inputs.
2. Cada `plugin.install`/`plugin.update` carrega a entrada completa de plugin: `id`, `name`, `version`, `source`, `content_hash` (hash canônico do diretório) e `manifest_path` portável. Instalação de ID ausente emite install; reinstalação de ID existente emite update. Remoção leva `plugin_id` e remove também todas as execuções desse plugin no estado projetado, reproduzindo o comportamento atual.
3. Cada evento de roadmap leva a chave `(plugin_id, execution_id)` e a entrada completa resultante: `plugin_version`, `roadmap`, `input` (relativo ou null), `input_sha256` (SHA-256 dos bytes ou null quando não há input), `content_hash` e `status`. Activate cria ou substitui a chave como active; pause/resume exigem chave existente e a deixam paused/active; deactivate exclui a entrada, como hoje. Remover entrada inexistente conserva o resultado idempotente atual. Informações temporais vêm apenas de `ts` do evento; não consultar relógio durante a projeção.
4. Caminhos do workspace são relativos POSIX, sem `..` ou caminhos absolutos. Para plugin empacotado ou externo, `source` identifica a origem de forma estável, e `manifest_path` é relativo à raiz dessa origem resolvida localmente. Não gravar diretórios absolutos de usuário. Um local de origem indisponível impede nova execução, mas não a reconstrução dos locks a partir dos eventos. A validação e cópia do input exigidas na ativação permanecem sob responsabilidade do comando; o evento retém caminho e hash, não promete backup dos seus bytes.
5. O projetor mantém mapas por ID de plugin e por `(plugin_id, execution_id)`. Materializa `.roadmap/plugins.lock.json` e `.roadmap/roadmaps.lock.json` usando o mesmo escritor atômico das outras projeções, com schema_version de lock existente, chaves ordenadas, indentação 2, UTF-8 sem escapes ASCII, newline final e listas ordenadas pelas chaves acima. Os campos preexistentes são preservados; `input_sha256` é extensão aditiva. Apagar os dois locks e executar `project` reconstrói bytes idênticos aos produzidos por essa mesma versão após a operação.
6. Os locks novos **não entram** no `projection_hash_sha256` atual. Não mudar o hash do log real nem os golden hashes existentes por esse motivo. A checagem de reconstrução dos locks é separada; eventos de log misto continuam válidos.
7. Compatibilidade e adoção: antes da primeira escrita de plugin/roadmap, se nenhum evento dessas famílias existir, ler ambos os locks legados sob o lock do store e validar toda a importação antes de efeitos. Emitir primeiro `plugin.install` para todos os plugins por ID, depois `roadmap.activate` para cada execução pela chave. Eventos de adoção carregam `adopted=true`; somente nessa adoção, activate aceita o status legado active/paused/deactivated e preserva a entrada e seu status integralmente. Nas operações novas, activate sempre produz active e deactivate exclui a entrada como antes. Input ausente em arquivo legado mantém caminho e hash null, com anotação de adoção; não fabricar bytes ou hash. Só então emitir a operação pedida, no mesmo lote. Nenhuma adoção parcial: falha de validação deixa log e locks intactos. A partir desse lote, o log é a autoridade. Sem primeira escrita, continuar lendo locks antigos e não apagá-los; project não os substitui por vazios. Store sem eventos dessas famílias e sem locks não ganha locks vazios.
8. `contract.set` leva `contract` (caminho relativo sob `.roadmap/` de contrato admitido) e `sha256`. O comando explícito é `esaa contract record --file <caminho-relativo>`; o mesmo registro é usado após migrate/revert. Nenhum evento quando não há alteração nem no dry-run. Preservar backups já existentes. O último hash por contrato é derivado do log. Verify acrescenta informação de contratos divergentes/ausentes/sem registro, sem alterar verify_status nem exit code. Contratos não são reescritos durante replay. Isso registra evidência dos bytes observados, sem prometer transação distribuída entre arquivo do contrato e log: se houver interrupção entre mudança e registro, verify mostra divergência, e o operador registra os bytes após diagnóstico.
9. `eligible` mantém a combinação de tarefas do log e tarefas planejadas, agora usando roadmaps ativos da projeção. Os testes devem cobrir todos os eventos, adoção, reconstrução idêntica, drift de contrato e dry-run, preservando a comparação das entradas legadas com as normalizações de portabilidade e o novo campo explicitamente documentados.

## Alternativas consideradas

- Manter locks como autoridade independente: não permite reconstrução/auditoria integral pelo log.
- Embutir conteúdo completo de plugins e contratos: amplia volume e não é necessário à decisão.
- Importar locks em toda leitura: escreve durante consultas e cria adoção implícita repetida.
- Incluir novos locks no hash existente: altera hashes históricos sem necessidade desta entrega.

## Consequências

Plugins e execuções tornam-se auditáveis e os locks descartáveis após adoção. O replay reconstrói metadados, não instala bytes de plugins ou inputs nem recria conteúdo de contratos. A portabilidade troca caminhos absolutos por referências à origem; as normalizações precisam ser explícitas nos checks de migração. Esta tarefa só documenta o alvo.

## Referências

**Este documento referencia:**

- [src/esaa/plugins.py:147 — `_write_plugins_lock`](../../src/esaa/plugins.py#L147)
- [src/esaa/plugins.py:163 — `_write_roadmaps_lock`](../../src/esaa/plugins.py#L163)
- [src/esaa/plugins.py:180 — `_hash_dir`](../../src/esaa/plugins.py#L180)
- [src/esaa/orchestrator_commit.py:56 — `commit_orchestrator_events`](../../src/esaa/orchestrator_commit.py#L56)
- [adr-0005](0005-contratos-ativos-templates.md)
- [adr-0008](0008-schema-append-upcasters.md)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado ARQ-03; ARQ-06; tarefa documental AUD-O2-090; implementação: AUD-O2-060.

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
