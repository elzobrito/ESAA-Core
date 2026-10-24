# Parecer da instância /root/preactivation_review

Decisão técnica: request_changes. Instância distinta do executor, mesmo runner codex. Não demonstra independência humana ou identidade criptográfica definitiva. Não emitiu eventos reais durante os testes.

## R1 — Replay/verify não autentica eventos

identity.py:119 project_registry aceita payloads; projector.py:327 ignora actor.bootstrap/register; projector.py:194 confia reviewer_role; service_core.py:223/455 verifica projeção, não assinaturas. Fixture: assinaturas de bootstrap/register/review zeradas; verify e replay(write_views=False) retornam ok. Entrada CLI normal verifica assinatura, mas não substitui verificação de histórico. Pré-condição: controle dos arquivos do projeto, explicitamente incluído pelo proprietário; não se alega exploração remota sem esse acesso.

## R2 — Âncora/ativação não resiste a adversário do projeto

identity.py:36 lê .roadmap/governance-anchor.json; identity.py:168 compara apenas com bootstrap do mesmo histórico. Fixture: trocar âncora e public_key_hex/fingerprint_sha256 do evento bootstrap, mantendo assinatura velha, permite cadastro assinado pela chave atacante. Segundo caso: remover eventos bootstrap/register e resequenciar restaura qa_role e review unsigned termina done. Troca isolada de anchor é rejeitada, controle insuficiente para troca conjunta/rollback. Não existe pinning externo demonstrado.

## R3 — Claimant/principal não autenticado

submission.py:180 exige identidade apenas no review; projector.py:170 grava claimant textual; identity.py:292 compara strings. Mesmo processo com chave QA faz claim/complete unsigned como reviewer-alias e review assinado reviewer-qa: accepted/done. Proibição de IDs iguais e chaves duplicadas não estabelece independência desse alias.

## Resultado positivo e ação requerida

Histórico confiável + bootstrap presente: review exige assinatura, escopo assinado liga ator/tarefa/decisão e nonce sequencial repetido é rejeitado. Compatibilidade histórica sem bootstrap funciona, mas rollback foi reproduzido. Solicitar correções governadas no footprint original; não ativar, não forjar segundo ator, não alterar TCG. Revisão administrativa pré-ativação não é prova criptográfica.
