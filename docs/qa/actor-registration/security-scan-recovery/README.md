# Recuperação do scan — BLOCKED_STORAGE

ESAA-OPS-ACTOR-SCAN-RECOVERY-001: diagnóstico concluído, publicação para review; não done nem scan de segurança concluído. Claimant agent-qa, runner codex. Código não alterado. Scan original cfe966df-2ad4-4d14-9f2d-c7354bf49a6d permanece running/discovery, sem report, sobre snapshot anterior. Current_patch_covered=false.

Preflight helper READY, 3 checks PASS. Tentativa de publicar preflight no scan: 'Preflight issues can only be updated during preflight.' Não forçado retorno de fase. Tentativa save persistent repetiu recusa do pai group/world writable sem sticky bit. Nenhum chmod, mudança de owner/config ou novo scan.

O pai imediato scans/ESAA-Core está 0775, owner/grupo elzobrito. O diretório do scan está 0700, mas não basta. A remediação de permissões é externa ao boundary da tarefa e requer operador/autorização específica. Não há ferramenta exposta para migrar diretório ou atualizar diffTarget do scan existente; update_scan_context só altera userContext, não snapshot. Após intervenção deve-se revalidar persistência e mecanismo oficial de cobertura do diff atual; nunca representar baseline anterior como patch atual.

Revisão manual pós-correção distinta encontrou autorização inválida descartada em registry inativo (identity.py340–369); parecer request_changes. Não equivale a scan gerenciado. Rollback/alias continuam pendentes de 002/003. Não READY_FOR_OWNER_BOOTSTRAP. Não houve bootstrap real, alteração TCG ou chave definitiva.
