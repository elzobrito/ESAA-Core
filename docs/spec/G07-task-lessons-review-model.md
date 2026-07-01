# G07 - Especificacao: Task Model, Lessons e Review Tipado

> Tarefa: T-G07-TASK-LESSONS-REVIEW-SPEC (spec)  
> Target: docs/spec/G07-task-lessons-review-model.md  
> Escopo: contrato canonico para evolucao backward-compatible do ESAA-Core.  
> Status: especificacao, sem implementacao do core nesta task.

## Objetivo

Definir a evolucao do modelo de tarefas, lessons e review do ESAA-Core para
que tarefas expressem melhor sua intencao operacional, seus criterios de aceite,
seu modo de revisao obrigatorio e suas relacoes historicas com outras tarefas.

A mudanca deve preservar os principios centrais do ESAA:

- `.roadmap/activity.jsonl` continua sendo a fonte da verdade.
- `.roadmap/roadmap.json`, `.roadmap/issues.json` e `.roadmap/lessons.json`
  continuam sendo projecoes deterministicamente reconstruiveis.
- O Orchestrator continua sendo o single writer do event store.
- Entradas invalidas falham antes de append no event store.
- Tasks antigas e roadmaps antigos continuam validos sem migracao obrigatoria.

## Decisoes Canonicas

### task_kind e task_type

`task_kind` continua controlando ator, boundary e tipo de intervencao permitido:

```text
spec | impl | qa
```

`task_type` descreve a intencao operacional da tarefa:

```text
feature | hotfix | audit | release | memory | governance | maintenance
```

Esses campos nao competem. Uma task pode ser, por exemplo, `task_kind=spec` e
`task_type=governance`, ou `task_kind=impl` e `task_type=hotfix`.

### required_verification, required_review_mode e acceptance_criteria

`required_verification` permanece o mecanismo canonico para checks exigidos.
Nao deve ser criado campo duplicado como `required_checks`.

`required_review_mode` define o modo de review obrigatorio para uma task. Na v1,
cada task pode exigir no maximo um modo obrigatorio:

```text
functional | security | regression | docs | governance | release
```

`acceptance_criteria` descreve criterios humanos e verificaveis de aceite. Na
v1, e uma lista ordenada de strings. A ordem e estavel e cada item pode ser
referenciado por indice, como `AC[0]`, `AC[1]` e `AC[2]`.

## Campos de Task

Todos os campos abaixo sao opcionais para compatibilidade com eventos e roadmaps
existentes.

### task_type

Campo autorado em `task.create`.

```json
{
  "task_type": "governance"
}
```

Valores validos v1:

```text
feature | hotfix | audit | release | memory | governance | maintenance
```

### acceptance_criteria

Campo autorado em `task.create`.

```json
{
  "acceptance_criteria": [
    "The spec defines optional task fields.",
    "The spec defines validation timing before append."
  ]
}
```

Regras:

- Deve ser uma lista ordenada de strings nao vazias.
- A ordem deve ser preservada em projection, dispatch-context e replay.
- Itens podem ser referenciados por indice estavel: `AC[0]`, `AC[1]`.

### required_review_mode

Campo autorado em `task.create`.

```json
{
  "required_review_mode": "governance"
}
```

Valores validos v1:

```text
functional | security | regression | docs | governance | release
```

Se presente, todo evento `review` da task deve informar `review_mode` igual ao
valor exigido, tanto para `approve` quanto para `request_changes`.

### supersedes

Campo autorado em `task.create`.

```json
{
  "supersedes": ["G06-001"]
}
```

Regras:

- Deve ser uma lista de task ids.
- Cada task referenciada deve existir na projecao no momento em que o evento
  `task.create` e processado.
- Nao pode conter o proprio `task_id`.
- Nao pode conter duplicados.
- Nao altera status da task referenciada.

### superseded_by

Campo derivado pelo projector. Nao deve ser aceito como input autorado.

```json
{
  "superseded_by": ["G07-001", "G07-002"]
}
```

Regras:

- Sempre e lista na projecao atual.
- Acumula task ids na ordem dos eventos `task.create` no `activity.jsonl`.
- Nao altera status da task referenciada.
- Deve ser tratado como dado de leitura no `dispatch-context`.

## Projection Rules

- `supersedes` e input autorado apenas em eventos `task.create`.
- `superseded_by` e projection-only e nunca deve ser autorado por usuario ou
  agente.
- `superseded_by` e sempre lista.
- `superseded_by` acumula task ids na ordem de ocorrencia dos eventos
  `task.create` no `activity.jsonl`.
- `supersedes` deve referenciar somente tasks que ja existem quando o evento
  `task.create` e processado.
- `supersedes` nao pode referenciar a propria task.
- `supersedes` nao pode conter duplicados.
- `supersedes` nao altera `status`, `assigned_to`, `started_at`,
  `completed_at`, `verification` ou qualquer outro campo historico da task
  referenciada.
- Campos opcionais ausentes em eventos antigos nao devem ser materializados como
  `null` incompativel. A projecao atual pode omitir o campo ou usar listas vazias
  para campos de colecao como `acceptance_criteria`, `supersedes` e
  `superseded_by`.

## Validation Timing

Entradas invalidas devem falhar antes de append no `activity.jsonl`.

Aplicacoes obrigatorias:

- `task.create` com `task_type` fora da enum v1 deve falhar antes de append.
- `task.create` com `required_review_mode` fora da enum v1 deve falhar antes de
  append.
- `task.create` com `acceptance_criteria` invalido deve falhar antes de append.
- `task.create` com `supersedes` inexistente, duplicado ou self-reference deve
  falhar antes de append.
- `review` com `review_mode` fora da enum v1 deve falhar antes de append.
- `review` sem `review_mode` em task que possui `required_review_mode` deve
  falhar antes de append.
- `review` com `review_mode` diferente de `required_review_mode` deve falhar
  antes de append.

Replay e verify devem aplicar as mesmas regras deterministicamente. Um event
store contendo evento invalido deve ser tratado como inconsistente/corrompido de
acordo com a politica ja usada pelo ESAA-Core para falhas de replay.

Eventos invalidos nao devem gerar evento `review`, evento `task.create`, evento
`output.rejected` nem qualquer mutacao de projecao. O erro deve ser retornado ao
chamador antes do append.

## Review Contract

`review` mantem as decisoes v1 existentes:

```text
approve | request_changes
```

O evento de review pode carregar `review_mode` opcional:

```json
{
  "decision": "approve",
  "review_mode": "governance"
}
```

Regras:

- Se a task nao possui `required_review_mode`, `review_mode` e opcional.
- Se `review_mode` for informado, deve pertencer a enum v1.
- Se a task possui `required_review_mode`, todo `review`, incluindo
  `request_changes`, deve informar `review_mode` igual ao exigido.
- Um review invalido por modo ausente, divergente ou fora da enum falha antes de
  append.
- O modo informado deve ser preservado no evento admitido e ficar disponivel
  para replay, auditoria e dispatch-context.

## Dispatch Context

O `dispatch-context` deve expor os campos novos para os agentes relevantes de
`spec`, `impl` e `qa`.

Campos esperados no slice da task quando existirem ou forem materializados:

```json
{
  "task": {
    "task_id": "G07-001",
    "task_kind": "spec",
    "task_type": "governance",
    "acceptance_criteria": [],
    "required_verification": {
      "checks": []
    },
    "required_review_mode": "governance",
    "supersedes": [],
    "superseded_by": []
  }
}
```

`superseded_by` deve ser apresentado como dado de leitura. Agentes nao devem
editar esse campo diretamente.

## Lessons Contract

Lessons continuam sendo projecao derivada do event store e constraints
operacionais injetadas no contexto quando relevantes.

### status

Valores v1:

```text
active | experimental | superseded | archived
```

Semantica:

- `active`: entra no dispatch-context normal e pode ter enforcement automatico.
- `experimental`: entra no dispatch-context normal, mas nao bloqueia execucao
  por padrao.
- `superseded`: permanece auditavel, mas nao entra no contexto normal.
- `archived`: permanece auditavel, mas nao entra no contexto normal.

### scope

Dimensoes permitidas:

```json
{
  "scope": {
    "task_kinds": ["spec"],
    "task_types": ["governance"],
    "review_modes": ["governance"],
    "paths": ["docs/spec/**"],
    "actors": ["agent-spec"],
    "runners": ["codex"]
  }
}
```

Semantica de filtro:

- Dentro da mesma dimensao, a combinacao e OR.
- Entre dimensoes diferentes, a combinacao e AND.

Exemplo: uma lesson com `task_types=["governance"]` e
`paths=["docs/spec/**"]` se aplica quando a task e de tipo `governance` E algum
path relevante casa com `docs/spec/**`.

### enforcement

`enforcement` deve ser objeto extensivel:

```json
{
  "enforcement": {
    "mode": "require_review_mode",
    "value": "security"
  }
}
```

Para casos simples, `value` pode estar ausente:

```json
{
  "enforcement": {
    "mode": "warn"
  }
}
```

Modos com enforcement seguro na v1:

```text
warn | require_check | require_note | require_review_mode
```

Modos documentados como futuros ou experimentais, sem enforcement automatico na
v1:

```text
require_field | require_step | require_boundary_grant
```

`require_boundary_grant` nunca amplia permissoes. Ele jamais deve conceder
boundary automaticamente. Em uma evolucao futura, esse modo so podera exigir que
um grant explicito ja existente autorize a acao; na ausencia desse grant, a
execucao deve falhar.

### source_refs

`source_refs` pode continuar flexivel, mas o formato recomendado e:

```json
{
  "source_refs": [
    {
      "type": "task",
      "id": "G07-001"
    },
    {
      "type": "review",
      "id": "EV-00000123"
    },
    {
      "type": "audit",
      "path": "docs/audit/security.md"
    }
  ]
}
```

## Canonical Examples

Os exemplos usam a nomenclatura atual do contrato ESAA-Core: `task_id`,
`task_kind`, `task.create` e `action: "review"`. Se implementacoes futuras
introduzirem aliases de apresentacao, eles devem ser normalizados para esses
nomes canonicos antes de persistencia, replay e verify.

### Task nova com campos opcionais

```json
{
  "task_id": "G07-001",
  "task_kind": "spec",
  "task_type": "governance",
  "title": "Specify task lessons and review model",
  "description": "Define optional task fields, typed review and lessons contract.",
  "status": "todo",
  "depends_on": [],
  "targets": ["docs/spec/G07-task-lessons-review-model.md"],
  "outputs": {
    "files": ["docs/spec/G07-task-lessons-review-model.md"]
  },
  "immutability": {
    "done_is_immutable": true
  },
  "acceptance_criteria": [
    "The spec defines optional task fields.",
    "The spec defines projection rules for superseded_by.",
    "The spec defines validation timing before append."
  ],
  "required_review_mode": "governance",
  "supersedes": []
}
```

### Task antiga projetada como substituida

```json
{
  "task_id": "G06-001",
  "status": "done",
  "superseded_by": ["G07-001", "G07-002"]
}
```

### Review tipado

```json
{
  "action": "review",
  "task_id": "G07-001",
  "prior_status": "review",
  "decision": "approve",
  "review_mode": "governance",
  "tasks": ["G07-001"]
}
```

### Lesson com scope e enforcement tipados

```json
{
  "lesson_id": "LES-0100",
  "status": "active",
  "title": "Governance tasks require governance review",
  "mistake": "Task de governanca foi aprovada por review generico.",
  "rule": "Tasks task_type=governance devem usar review_mode=governance.",
  "scope": {
    "task_types": ["governance"],
    "paths": ["docs/spec/**"]
  },
  "enforcement": {
    "mode": "require_review_mode",
    "value": "governance"
  },
  "source_refs": [
    {
      "type": "task",
      "id": "G07-001"
    }
  ]
}
```

## Backward Compatibility

Implementacoes da G07 devem preservar compatibilidade com:

- Eventos antigos de `task.create` sem campos novos.
- Roadmaps antigos sem `task_type`, `acceptance_criteria`,
  `required_review_mode`, `supersedes` ou `superseded_by`.
- Reviews antigos sem `review_mode`, desde que a task tambem nao possua
  `required_review_mode`.
- Lessons antigas com o shape atual de `scope` e `enforcement`.

Campos novos devem ser opcionais no schema. A ausencia de campo novo nao deve
alterar a semantica historica da task.

Implementacoes futuras devem aceitar o shape legado de lessons e normaliza-lo
internamente para o contrato G07 quando necessario, sem exigir migracao manual.

## Non-Goals

Esta spec nao deve:

- Implementar mudancas no core nesta task.
- Migrar roadmaps antigos.
- Criar novos `task_kind` alem de `spec`, `impl` e `qa`.
- Expandir decisoes de review alem de `approve` e `request_changes`.
- Implementar enforcement automatico para `require_field`, `require_step` ou
  `require_boundary_grant` na v1.
- Permitir multiplos `required_review_mode` por task na v1.
- Transformar lessons em mecanismo de concessao automatica de boundary.

## Acceptance Criteria

- AC[0]: A spec define campos opcionais para `task_type`,
  `acceptance_criteria`, `required_review_mode`, `supersedes` e
  `superseded_by`.
- AC[1]: A spec define `supersedes` como input autorado e `superseded_by` como
  projection-only.
- AC[2]: A spec define regras de projecao para `superseded_by` como lista em
  ordem de eventos.
- AC[3]: A spec define timing de validacao antes de append para `task.create` e
  `review`.
- AC[4]: A spec define contrato de lessons com status, scope, filtro e
  enforcement.
- AC[5]: A spec declara non-goals e impede implementacao prematura nesta task.
- AC[6]: A spec inclui exemplos canonicos de task, task supersedida, review
  tipado e lesson tipada.

## Future Implementation Test Matrix

Uma task posterior de implementacao deve cobrir pelo menos:

- Roadmap/eventos antigos sem campos novos continuam validos.
- Campos opcionais ausentes nao sao materializados como `null` incompativel.
- `task create` preserva `task_type`, `acceptance_criteria`,
  `required_review_mode` e `supersedes`.
- `acceptance_criteria` preserva ordem.
- `supersedes` inexistente, duplicado ou self-reference falha antes de append.
- Duas tasks supersedendo a mesma task geram `superseded_by` ordenado por ordem
  de evento.
- `supersedes` nao muda status da task substituida.
- Review sem `review_mode` em task que exige modo nao escreve evento.
- Review com modo errado ou enum invalida nao escreve evento.
- Review `request_changes` tambem exige modo correto.
- Review com modo valido em task sem exigencia e aceito e preservado.
- `dispatch-context` expoe `superseded_by` como dado de leitura.
- Lessons `experimental` aparecem no contexto sem bloquear.
- Lessons `superseded` nao aparecem no contexto ativo.
- Filtro de lessons aplica OR por dimensao e AND entre dimensoes.

Checks esperados para a task posterior:

```bash
PYTHONPATH=src pytest -q
esaa --root . verify
```
