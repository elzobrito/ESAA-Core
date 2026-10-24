# Revisão pré-ativação — ESAA Core

Data: 2026-10-02 UTC. Parecer técnico: **request_changes**. NÃO ATIVAR.

Tarefa de implementação: ESAA-CORE-ACTOR-REGISTRATION-001, claimant agent-impl, entrada review seq 848. Publicação separada: ESAA-CORE-ACTOR-PREACTIVATION-REVIEW-001, claimant agent-qa. Empacotamento: ESAA-CORE-ACTOR-PACKAGING-001, todo; boundary do manifesto precisa regularização oficial antes de claim.

Base Git: 6122d59b13569976d5537399c7ded532efa75cb4, CLI 0.5.0b19; implementação existe em worktree dirty, NÃO commit congelado. identity_contract real inactive, zero atores criptográficos, bootstrap null. Nenhum bootstrap real/chave definitiva/commit/push/correção de produto foi realizado. TCG não foi tocado; seu DRAFT_BLOCKED relatado permanece precondição externa, não foi reavaliado.

## Evidência

Suíte completa reexecutada: 433 passed in 27.20s. Suíte de atores pelo avaliador: 16 passed in 2.66s. Quatro testes adversariais reproduzem comportamentos indevidos: 4 passed in 0.95s (isto NÃO significa segurança PASS). Ver tests-and-transition.md e fixture-reproductions.py. Diff completo do footprint de implementação em implementation.patch, não inclui plugins.py/test_plugin_manager.py preexistentes. Alteração dirty de pyproject.toml já existia; hash preservado, regularização separada, sem instalação limpa nesta revisão.

## Independência e limite

Avaliador /root/preactivation_review em instância fresca, sem contexto de implementação e sem participação em GT/oracle/resultados TCG; parecer fornecido antes de qualquer evento administrativo seu. Mesmo runner codex; separação de instância não prova independência humana nem identidade criptográfica. Registry histórico autoriza agent-qa; review pré-ativação sob qa_role NÃO certifica autenticação criptográfica. Publicador não deve autoaprovar sua tarefa QA.

## Bloqueadores

1. Replay/verify não verifica assinaturas dos eventos de identidade/review.
2. Âncora e estado ativo dependem de arquivos locais mutáveis: troca conjunta e rollback permitem autoridade atacante/fallback qa_role.
3. Claim/complete não autentica principal: revisor assinado aprova seu alias unsigned.

Com histórico íntegro e bootstrap presente, assinatura inválida falha fechada sem fallback. Essa garantia é condicional; os ataques de rollback e alias tornam insuficiente a autorização para ativação.

## Skill de segurança

Usado codex-security:security-diff-scan, com fases validation e attack-path-analysis, scan cfe966df-2ad4-4d14-9f2d-c7354bf49a6d. Candidatos e avaliações registrados no MCP do plugin, separado de ESAA. Publicação suplementar recusada por permissões group-writable do diretório gerenciado; não houve chmod nem alegação de scan gerenciado concluído. Este pacote ESAA é evidência pré-ativação, não substitui um completed scan do plugin.

Recibos finais são eventos append-only do Orchestrator; consultar state/verify e events após esta publicação. Esta entrega não declara done da implementação.
