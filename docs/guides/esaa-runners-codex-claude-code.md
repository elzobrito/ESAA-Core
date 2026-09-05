# Operando Codex e Claude Code como runners do ESAA

🌐 **Português** · [English](esaa-runners-codex-claude-code.en.md)

O ESAA não usa MCP. Runners integram-se por CLI local e arquivos.
Use as seções necessárias à ação atual; este guia não é uma sequência obrigatória.

## Identidade e contexto

Runner é o software executor; actor é o papel lógico. O mesmo runner pode operar
papéis distintos, mas isso não demonstra revisão por outro modelo ou humano.
O Orchestrator valida e aplica efeitos; o actor que reivindica é quem completa.

```bash
python -m esaa --root <workspace> --runner codex <command> ...
```

Troque `codex` pelo runner real; alternativamente configure `ESAA_RUNNER_ID`.
Em modo strict, o runner precisa estar registrado em `.roadmap/agents_swarm.yaml`.
Não inclua `runner` no envelope: o Orchestrator carimba a proveniência.

```bash
python -m esaa eligible
python -m esaa state T-EXAMPLE
python -m esaa dispatch-context T-EXAMPLE
```

`dispatch-context` traz `task`, ações permitidas, `schema_slice` e correlação.
Lessons são filtradas por ação e escopo. Em `complete`, há boundaries, interfaces
das dependências e issues filtradas; em `review`, verificações da entrega quando
disponíveis. Perfil do projeto e capacidades do runner dependem do cadastro local.
O corpo de specs e arquivos não é garantido no contexto: recupere as referências
necessárias, sem varrer todo o repositório. Boundaries de leitura são permissões,
não uma lista de arquivos a carregar integralmente.

## Claim, entrega e revisão

`claim` e `complete` são submissões distintas, com uma `activity_event` por envelope
e `prior_status` coerente. Isso não limita a tarefa a duas invocações: revisão,
correções e novas tentativas seguem a máquina de estados.
JSON puro se aplica aos envelopes submetidos, não à conversa com o usuário.

### Claim

Para uma tarefa `todo` elegível:

```json
{"activity_event":{"action":"claim","task_id":"T-EXAMPLE","prior_status":"todo"}}
```

```bash
python -m esaa --runner codex submit --actor agent-impl claim.json
```

### Complete e efeitos de arquivos

Para `in_progress`, o actor responsável entrega artefatos e verificações reais:

```json
{
  "activity_event": {
    "action": "complete",
    "task_id": "T-EXAMPLE",
    "prior_status": "in_progress",
    "verification": {"checks": ["affected behavior verified"]}
  },
  "file_updates": [{"path": "src/example.py", "content": "VALUE = 1\n"}]
}
```

O exemplo pressupõe tarefa impl com o caminho autorizado; adapte aos critérios
da tarefa. `file_updates` é permitido somente com `complete`; efeitos finais são
do Orchestrator. Uma entrada também pode usar edits exatos no lugar de `content`:

```json
{
  "path": "src/example.py",
  "base_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "edits": [{"old_string": "VALUE = 1", "new_string": "VALUE = 2", "replace_all": false}]
}
```

Substitua o hash ilustrativo pelo SHA-256 dos bytes atuais do arquivo.
Os edits são aplicados progressivamente ao texto UTF-8; preserve os newlines
exatos, inclusive CRLF. Múltiplos matches exigem `replace_all=true`; arquivos
não UTF-8 são rejeitados. Códigos: `EDIT_BASE_MISMATCH`, `EDIT_TARGET_NOT_FOUND`,
`EDIT_AMBIGUOUS`, `EDIT_INVALID`. A resolução precede validação dos efeitos,
limites de recursos, staging e artefatos.

```bash
python -m esaa --runner codex submit --actor agent-impl complete.json --dry-run
python -m esaa --runner codex submit --actor agent-impl complete.json
python -m esaa verify
```

O dry-run é opcional. Antes de complete, atenda aos critérios de aceitação e
execute as verificações pertinentes; quando solicitado, prossiga por execução,
inspeção e correção. Mínimos do contrato: spec/impl/qa = 1 check; hotfix = 2.
Complete não significa aprovação nem autorização de publicação.

### Review e done

```json
{"activity_event":{"action":"review","task_id":"T-EXAMPLE","prior_status":"review","decision":"approve","tasks":["T-EXAMPLE"]}}
```

```bash
python -m esaa --runner codex review T-EXAMPLE --actor agent-qa --decision approve
```

A política `review_authorization=qa_role` admite papéis QA/orchestrator;
um owner sem esse papel recebe `REVIEW_ROLE_VIOLATION`. Observe o modo de revisão
exigido pela tarefa. `request_changes` retorna a `in_progress`; `approve` chega a
`done`. Não reabra done: reporte issue e siga hotfix, preservando a tarefa original.
Em issue sobre done, `prior_status` deve ser `done`.

## Autonomia e impedimentos

Consultas são somente leitura, sem transições; relate resultado e limites úteis.
Dentro do escopo autorizado, investigue informação acessível e resolva escolhas
locais reversíveis sem aprovação a cada passo. A preparação e validação local
não autorizam efeitos finais diretos nem operações externas ainda não autorizadas.

Obtenha decisão antes de alterar requisitos materiais ou permissões. Reporte
impedimentos persistentes de contexto, dependência ou boundary com evidências;
a ausência de informação no prompt, por si só, não demonstra impedimento.

```json
{
  "activity_event": {
    "action": "issue.report",
    "task_id": "T-EXAMPLE",
    "prior_status": "in_progress",
    "issue_id": "ISS-EXAMPLE",
    "severity": "medium",
    "title": "Required dependency is unavailable",
    "evidence": {"symptom": "Required source cannot be obtained", "repro_steps": ["Inspect the dependency reference"]}
  }
}
```

Lessons em `reject`, `require_field` e `require_step` são obrigatórias.
`warn` deve ser considerado, sem impor bloqueio ou texto fixo de reconhecimento
que não esteja exigido pela própria lesson.

## Concorrência e integridade

O runtime atual possui locks com PID, host e data, releitura transacional sob lock
e verificação após append. A CLI trata contenção e recuperação de locks conforme
suas regras; não remova locks manualmente. Não generalize essas garantias para
versões antigas ou para edição concorrente nos mesmos arquivos.

Não assuma tarefas de outro responsável. Interrompa a operação afetada por
`STORE_LOCK_TIMEOUT`, `JSONL_INVALID`, `EVENT_SEQ_*`, `APPEND_VERIFY_FAILED` ou
falha de integridade. Não contorne o erro. Conflitos de estado são tratados pelo
runtime; se persistirem, recupere o contexto antes de nova submissão válida.
Após escrita governada, execute `verify`.

## Referências operacionais

Gates, campos e limites vêm de `.roadmap/AGENT_CONTRACT.yaml`,
`ORCHESTRATOR_CONTRACT.yaml`, `agent_result.schema.json` e `RUNTIME_POLICY.yaml`.
Os defaults de tentativas são 3, cooldown de 2 minutos e TTL de 30 minutos;
`PRIOR_STATUS_MISMATCH` não consome tentativa. Consulte a política instalada.

Quando o ambiente exigir orientação especializada de comandos, registre suas
capacidades reais. O registro é local ao workspace e só então é injetado no despacho.
Telemetria deve registrar valores observados; não invente tokens ou custos.

```bash
python -m esaa --runner codex input commands register <capabilities.yaml>
python -m esaa --runner codex input commands show
python -m esaa runner metrics --help
```

Os comandos diretos de transição evitam uma chamada LLM adicional; não substituem
a avaliação necessária para decidir uma revisão. Perfis PARCER são referências
por papel, não pré-requisito de leitura para todas as tarefas.

## Veja também

- [Primeiros passos](esaa-getting-started.md)
- [Referência do CLI](esaa-cli-reference.md)
- [Por que usar o ESAA](esaa-why.md)
