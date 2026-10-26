# Modelo de atacante (pré-ativação)

1. Substituir âncora + bootstrap no workspace e recalcular a chain.
2. Rollback para histórico pré-bootstrap e restaurar qa_role.
3. Claim/complete unsigned com alias e review signed no mesmo principal.
4. Fornecer authorization inválida com contrato inativo e degradar para legado.
5. Registrar actor cujo id já é alias, ou alias que colide com actor.
6. Completar tarefa de outro principal.
7. Impersonar orchestrator.

Controles observados nos testes de fixture: TRUST_MISMATCH / TRUST_ROLLBACK / BLOCKED_ENVIRONMENT / SELF_REVIEW_FORBIDDEN / PRINCIPAL_UNBOUND / ACTOR_BOOTSTRAP_REQUIRED / ACTOR_DUPLICATE / LOCK_VIOLATION / ORCHESTRATOR_IMPERSONATION.
