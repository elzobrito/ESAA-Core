# Auditoria complementar — candidato 0.5.0b22

Data: 2026-10-26. Executor: runner grok, actor agent-qa. Sem bootstrap, sem chaves definitivas, sem TCG.

## Escopo

Módulos `identity.py`, `identity_history.py`, `trust_root.py`, `trust_enrollment.py`, `actor_admin.py`, `submission.py`, `file_effects.py`, `verification_candidate.py`. Testes observados: 107 passed (canonical identity, closeout authorization, actor registration, trust rollback, signed replay).

## Achados fechados nos bytes atuais

1. Contrato inativo + `authorization` não nula → `ACTOR_BOOTSTRAP_REQUIRED` (claim/complete/review, API e CLI, dry-run incluso). `authorization=None` legado preservado.
2. Contrato ativo exige envelope Ed25519; claim/complete/review carimbam `_principal_id` / `_alias_id`; complete compara principal do claim; review exige principal distinto.
3. `actor.bind_alias` owner-signed; alias não colide com actor registrado; actor não pode reusar namespace de alias.
4. Pin `esaa.identity.trust.v2` fora do workspace; enrollment pelo perfil OS (`pwd.getpwuid`); replica `.roadmap/governance-anchor.json` não autoenrolla; troca conjunta âncora/história e rollback pré-bootstrap rejeitados.
5. Staging: o candidato em memória decide os bytes finais (hotfix ISS-ESAA-STAGED-CANDIDATE-20261026 já resolved).

## Limites

- Scan gerenciado `cfe966df-2ad4-4d14-9f2d-c7354bf49a6d` não persistiu; esta auditoria não herda a cobertura daquele snapshot.
- Independência administrativa usa `qa_role` (identidade viva inactive). Não é prova criptográfica de revisor distinto após bootstrap.
- ISSUE-ESAA-CORE-ACTOR-BOOTSTRAP-AUTHORITY-001 permanece: provisionamento do owner.

## Parecer

Código de identidade/trust do candidato é adequado para publicação da biblioteca com contrato **inactive**. **Não** READY_FOR_OWNER_BOOTSTRAP.
