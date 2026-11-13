---
titulo: "ADR 0001 — Identidade de ator inativa por padrão"
tipo: "Registro de decisão arquitetural"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# ADR 0001 — Identidade de ator inativa por padrão

**Sumário:** Status · Contexto · Decisão · Alternativas consideradas · Consequências · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## Status

Aceito — comportamento existente; não ativa identidade neste workspace.

## Contexto

No modo sem bootstrap, o chamador declara `--actor` e `--runner`. O primeiro identifica o papel contratual; o segundo identifica o veículo de execução. [src/esaa/events.py:16 — `make_event`](../../src/esaa/events.py#L16) carimba a proveniência resolvida por [src/esaa/provenance.py:27 — `resolve_runner`](../../src/esaa/provenance.py#L27). A declaração não prova posse de uma chave. A extensão Ed25519 é opcional e seu registro só se torna ativo após `actor.bootstrap` ([src/esaa/identity.py:145 — `project_registry`](../../src/esaa/identity.py#L145)).

## Decisão

Manter o modo declarativo como padrão para adoção simples, execução local e históricos existentes. Os gates de workflow, ownership por ator e boundaries continuam aplicáveis; eles não autenticam a pessoa por trás do nome. `runner_validation=permissive` aceita identificadores declarados; `strict` exige que estejam registrados, sem transformar esse registro em autenticação ([src/esaa/runtime_policy.py:233 — `validate_runner_id`](../../src/esaa/runtime_policy.py#L233)).

Quando o proprietário ativa Ed25519, `claim` e `complete` exigem autorização assinada vinculada à operação, tarefa, projeto e nonce ([src/esaa/identity.py:378 — `authorize_actor_transition`](../../src/esaa/identity.py#L378)); ownership e review usam o principal canônico ([src/esaa/identity.py:414 — `assert_review_identity`](../../src/esaa/identity.py#L414), [src/esaa/identity.py:519 — `authorize_agent_event`](../../src/esaa/identity.py#L519)). A ativação exige importação explícita de pin externo e enrollment do proprietário ([src/esaa/trust_root.py:121 — `require_pin_for_activation`](../../src/esaa/trust_root.py#L121), [src/esaa/trust_root.py:82 — `import_trust_pin`](../../src/esaa/trust_root.py#L82)). O checkpoint externo compromete histórico e projeção, conforme [src/esaa/trust_root.py:278 — `_assert_monotonic_checkpoint`](../../src/esaa/trust_root.py#L278). Não há ativação automática nem autenticação criptográfica do campo runner pelo simples carimbo.

A orientação HMAC/`identity.strict` de [g03-identidade](../spec/G03-actor-identity.md) é histórica; o protocolo atual de autenticação é Ed25519. [g08-proveniencia](../spec/G08-runner-provenance.md) documenta a proveniência operacional, sem substituir autenticação.

## Alternativas consideradas

- Exigir identidade criptográfica em todo workspace: aumenta configuração e custódia de chaves, além de alterar o fluxo legado.
- Tratar nomes de runner ou cadastro no swarm como autenticação: não demonstra posse de segredo.
- Ativar confiança a partir da réplica do próprio projeto: não estabelece autoridade independente.

## Consequências

A instalação padrão permanece acessível e compatível; o operador assume a confiança no chamador e no host. Ed25519 fornece verificação das autorizações e vínculos de principal; pin externo e enrollment acrescentam detecção de rollback e reescrita dentro das premissas do modelo. Host, Orchestrator, chaves e registros externos protegidos integram a base confiável. Mesmo UID, host ou proprietário comprometido ficam fora da garantia. Estes limites constam em [modelo-ameacas](../security/threat-model.md); a decisão não certifica segurança de produção.

## Referências

**Este documento referencia:**

- [g03-identidade](../spec/G03-actor-identity.md)
- [g08-proveniencia](../spec/G08-runner-provenance.md)
- [modelo-ameacas](../security/threat-model.md)
- [src/esaa/identity.py:519 — `authorize_agent_event`](../../src/esaa/identity.py#L519)
- [src/esaa/provenance.py:37 — `validate_runner_block`](../../src/esaa/provenance.py#L37)
- [auditoria-esaa-20261110](../audit/ESAA-CORE-AUDIT-2026-11-10.md) — achado SEC-02; ARQ-06; tarefa documental AUD-O2-090; implementação: comportamento existente; este ADR não altera código.

**Este documento é referenciado por:**

- [indice-adrs](README.md) — índice das decisões centrais.
