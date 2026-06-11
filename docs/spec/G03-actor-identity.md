# G03 - Especificacao: Identidade e autorizacao de actors

> Tarefa: T-007 (spec) - Target: SEC-02
> Roadmap: correction-plan
> Relacao com G08: `runner` identifica o principal/veiculo; `actor` continua sendo o papel autorizado pelo workflow.

## Problema

O runtime atual resolve `role` a partir de `.roadmap/agents_swarm.yaml`, mas ainda possui fallback heuristico: nomes com prefixo `agent-qa` viram role `qa`, `agent-orchestrator` vira `orchestrator`, e os demais viram `agent`. Isso enfraquece o modelo de autorizacao: uma string de actor pode ganhar capacidade de review sem registro explicito no swarm.

G03 fecha essa lacuna sem misturar responsabilidades:

1. `runner` autentica quem executa o comando.
2. `actor` declara o papel contratual que sera autorizado.
3. `agents_swarm.yaml` e a fonte de autorizacao de roles.
4. O Orchestrator valida tudo antes de workflow gates e antes de qualquer efeito.

## SEC-02 - Registro obrigatorio de actors

`agents_swarm.yaml` deve conter todos os actors permitidos:

```yaml
agents:
  agent-spec:
    display_name: "agent-spec"
    role: "specification"
  agent-impl:
    display_name: "agent-impl"
    role: "implementation"
  agent-qa:
    display_name: "agent-qa"
    role: "qa"
```

Regras:

1. Em modo `identity.strict=true`, qualquer submit com `actor` ausente do swarm falha com `ACTOR_UNKNOWN` antes de validar output de agente.
2. `resolve_role(actor, root)` nao usa mais prefixo como fonte de role quando `identity.strict=true`.
3. O modo legado continua disponivel com `identity.strict=false`; nele o fallback pode existir, mas deve emitir warning estruturado no resultado ou em telemetry futura.
4. `review` em `review_authorization=qa_role` exige role resolvida em `{qa, orchestrator}` pelo swarm, nunca por payload do agente.
5. `complete` continua protegido por WG-004: o actor que completa deve ser o mesmo que reivindicou a task.

Novos reject codes:

- `ACTOR_UNKNOWN`: actor nao registrado no swarm quando strict.
- `ACTOR_AUTH_FAILED`: autenticacao forte exigida e credencial ausente/invalida.

Ambos entram em `reject_codes.ALL_CODES` e no inventory test.

## Autenticacao forte opcional

A politica ganha bloco:

```yaml
identity:
  strict: true
  auth:
    mode: "none"        # none | hmac
    token_env_prefix: "ESAA_ACTOR_TOKEN_"
    clock_skew_seconds: 60
```

Modo `none` valida somente registro/autorizacao do actor. Modo `hmac` autentica o runner para exercer o actor:

1. O CLI aceita `--auth-token` nos comandos de agente (`submit`, `claim`, `complete`, `review`, `issue report`).
2. O service calcula o nome esperado da variavel de ambiente a partir do actor normalizado, por exemplo `ESAA_ACTOR_TOKEN_AGENT_QA`.
3. O token recebido e comparado em tempo constante com o segredo configurado.
4. Falha gera `ACTOR_AUTH_FAILED` antes de workflow gates e antes de staging de file effects.
5. O token nunca e persistido em event store, metrics, notes, file effects ou projection.

HMAC assinado com timestamp pode ser adicionado como extensao do modo `hmac` sem alterar a semantica principal: o Orchestrator autentica o direito de vestir o papel, nao o conteudo do envelope.

## Ordem de validacao no submit

A ordem esperada em `service.submit` e comandos equivalentes:

1. Parse do event store.
2. Carregamento de policy e swarm.
3. Validacao de runner conforme G08 (`RUNNER_UNKNOWN` se strict).
4. Validacao de actor (`ACTOR_UNKNOWN`).
5. Validacao de auth (`ACTOR_AUTH_FAILED`) quando habilitada.
6. Validacao schema/contrato do output.
7. Workflow gates (prior_status, allowed action, lock, review role).
8. Staging de `file_updates`.
9. Append transacional e commit dos efeitos.

Essa ordem garante fail-closed: actor invalido nao consome attempt de task por erro de agente, nao aplica arquivo e nao avanca estado.

## Compatibilidade

- Workspaces existentes podem iniciar com `identity.strict=false`, mas o workspace template do framework deve declarar `true`.
- `agent-mock` permanece registrado para fixtures deterministicas.
- `orchestrator` pode ser tratado como actor reservado implicitamente apenas para eventos reservados do Orchestrator. Para outputs de agente, deve seguir a politica de actor.
- Eventos legados continuam reprocessaveis: a validacao de identidade aplica-se a novos submits, nao muda eventos historicos.

## Criterios de aceite

1. `agent-qa-fake` sem registro nao pode aprovar review, mesmo com prefixo `agent-qa`.
2. Actor nao registrado falha com `ACTOR_UNKNOWN` antes de qualquer file effect.
3. Token invalido ou ausente em modo `hmac` falha com `ACTOR_AUTH_FAILED`.
4. Modo compatibilidade preserva comportamento legado com warning explicito.
5. WG-004 continua bloqueando complete por actor diferente do claim.
6. Inventory test confirma `ACTOR_UNKNOWN` e `ACTOR_AUTH_FAILED` em `ALL_CODES`.

## Fora de escopo

- Hash chain e reviewer_role forense pertencem a G02.
- Proveniencia de runner ja foi coberta em G08.
- Rotacao/armazenamento seguro de segredos fora de variavel de ambiente fica para hardening operacional posterior.