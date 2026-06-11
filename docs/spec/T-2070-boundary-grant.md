# T-2070 — Boundary grant por tarefa via `task.create` do operador

## Motivação

O modelo de boundaries por `task_kind` não tem mecanismo de extensão por tarefa.
Quando uma tarefa legítima precisa escrever fora da allowlist do seu kind
(ex.: `tools/audit/**`), o operador hoje edita o contrato vivo
`.roadmap/AGENT_CONTRACT.yaml` temporariamente e reverte depois. Isso tem três
defeitos conhecidos:

1. A concessão não deixa rastro no event store — a autorização vive num diff
   de YAML que desaparece na reversão; auditoria futura vê um efeito fora do
   boundary canônico sem o grant correspondente.
2. Durante a janela, a allowlist ampliada vale para **todas** as tasks em voo,
   não só para a que precisa (violação de menor privilégio).
3. `tests/test_state_machine_and_dispatch.py::test_minimal_context_changes_with_state`
   fica vermelho enquanto a extensão vigora.

Casos concretos: `ISS-T2031-BOUNDARY` (impl precisava escrever
`tools/audit/critical_findings.py`) e `ISS-AUDIT-RESOLVE-PAYLOAD-SHAPE`
(fix de uma linha em `tools/audit/traceability_and_report.py`).

## Conceito

`task create` — comando que **só o operador executa** (actor `orchestrator`) —
ganha um campo opcional `boundary_grant`: uma lista de padrões fnmatch de
paths de escrita adicionais, válidos **apenas para aquela task**. O grant é
gravado no payload do evento `task.create` no event store: auditável,
replayável e imutável como qualquer outro evento.

```powershell
python -m esaa --root . --runner claude-code task create T-XXXX --kind impl `
  --title "..." --boundary-grant "tools/audit/**" --output tools/audit/x.py
```

## Modelo de autorização

- A autoridade do grant deriva da superfície de comando: `task.create` não é
  uma action de agente (não passa por `submit`), logo agentes não conseguem
  conceder grants a si mesmos. O Orchestrator carimba `actor=orchestrator` e o
  runner de quem executou.
- O grant não é configurável pelo contrato nesta versão (engine-nativo): não
  há flag em `AGENT_CONTRACT.yaml` para habilitá-lo ou desabilitá-lo. O
  contrato canônico permanece intocado — o teste de boundaries continua verde.

## Semântica de enforcement (`_validate_boundaries`)

Para cada item de `file_updates`, na ordem:

1. **Safe-path sempre** (`_validate_safe_path`): path relativo, sem traversal.
   O grant não relaxa esta etapa.
2. **runtime:// não é afetado**: paths `runtime://` seguem exclusivamente as
   regras de external effects existentes; grant não os autoriza.
3. **Allowlist do kind OU grant**: o path precisa casar (fnmatch) com a
   allowlist `write` do `task_kind` **ou** com algum padrão de
   `boundary_grant` da task. Caso contrário, `BOUNDARY_VIOLATION`.
4. **`forbidden_write` prevalece sobre o grant**: path que casa com a denylist
   do kind é rejeitado mesmo se coberto pelo grant. Em particular,
   `.roadmap/**` permanece inacessível a agentes (princípio do single writer).
5. **`scope_patch` de hotfix continua valendo**: em tasks hotfix, o prefixo de
   `scope_patch` restringe todos os paths, inclusive os cobertos por grant.

## Validação na criação (`create_task`)

Cada padrão de `boundary_grant` é validado; violação rejeita com
`SCHEMA_INVALID` sem gravar evento:

- não-vazio, relativo (não inicia com `/` nem unidade `X:`);
- sem traversal (`..` em qualquer segmento);
- não pode iniciar com `runtime://`;
- não pode mirar a área de governança: padrão igual a, ou contido em,
  `.roadmap/**` é rejeitado na origem.

## Projeção e dispatch

- `projector._new_task` copia `boundary_grant` do payload para a task no read
  model (campo opcional, qualquer kind, não restrito a hotfix).
- `roadmap.schema.json` (`$defs.task`) ganha a propriedade opcional
  `boundary_grant` (array de strings, `minItems: 1`).
- `dispatch-context` expõe `boundary_grant` no bloco `task` (junto aos demais
  campos opcionais), para o agente saber o que pode escrever.

## Rollout

1. Template `src/esaa/templates/roadmap.schema.json` atualizado pela impl.
2. O artefato vivo `.roadmap/roadmap.schema.json` é sincronizado pelo operador
   a partir do template (cópia), pois `task create` valida a projeção contra o
   schema vivo e agentes não escrevem em `.roadmap/**`.
3. Nenhuma migração de eventos: tasks sem o campo seguem válidas; o campo é
   opcional no schema e na projeção.

## Fora de escopo (v1)

- Grant em `hotfix create` (o fluxo de hotfix continua usando `scope_patch`).
- Grant de leitura (boundaries `read` não mudam).
- Expiração/TTL de grant: o grant morre com a task (status `done` é terminal).
- Habilitação/configuração via contrato.

## Critérios de aceite (verificáveis na QA — T-2072)

1. `task create --boundary-grant` grava o campo no payload do evento e na
   projeção; `dispatch-context` o expõe.
2. `complete` com `file_updates` fora da allowlist do kind é **aceito** quando
   coberto por grant da própria task e **rejeitado** (`BOUNDARY_VIOLATION`)
   sem grant — inclusive para outra task sem grant no mesmo store.
3. Grant não sobrepõe `forbidden_write` (ex.: `.roadmap/x` rejeitado mesmo com
   grant `**`).
4. Padrões inválidos (`../x`, `runtime://x`, `.roadmap/**`, vazio) rejeitam o
   `task create` com `SCHEMA_INVALID` e nenhum evento é gravado.
5. Replay determinístico: projeção idêntica ao rematerializar os eventos.
