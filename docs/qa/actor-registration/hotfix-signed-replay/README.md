# Hotfix signed replay — entrega parcial pré-ativação

001 e integração CALLERS estão em review, claimant agent-impl, runner codex. Não há done nem READY_FOR_OWNER_BOOTSTRAP. Parent registration continua review. 002/003/004 e packaging permanecem todo.

Baseline HEAD 6122d59b13569976d5537399c7ded532efa75cb4, worktree dirty preservado, CLI 0.5.0b19, seq 879. Publicação código seq 910/914, verify ok. Sem commit, bootstrap real, credencial definitiva ou alteração TCG.

Suíte final REAL: 477 PASS em 33.90s; scratch: 477 PASS em 34.00s. 44 testes novos. Os quatro testemunhos históricos foram executados intactos antes/depois: antes 4 pass (vulnerabilidade); depois 2 fail/2 pass pois afirmam comportamento vulnerável, não são a suíte de regressão. Assinatura inválida é rejeitada. Substituição de âncora é interceptada antes de completar a adulteração conjunta; não prova proteção contra substituição conjunta reassinada. Rollback e alias ainda reproduzíveis, pertencem a 002/003.

Revisor separado /root/signed_replay_reviewer encontrou normalização que descartava autenticação e emitiu request_changes técnico, sem evento de aprovação. Executor confirmou, corrigiu e adicionou regressões. Não houve nova aprovação independente pós-correção; mesmo runner codex não prova identidade criptográfica distinta. É necessário parecer autorizado antes de done; 002 depende formalmente de 001 done, 004 depende dos quatro done.

Packaging: boundary do manifesto pendente de concessão oficial; não duplicado. Scanner gerenciado pendente por recusa de armazenamento e sobre baseline anterior, não cobre este patch. Resultado global: NOT_READY; rollback/alias e auditoria integrada faltantes.
