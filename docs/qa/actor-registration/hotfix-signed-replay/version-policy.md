# Política de autenticação

Epoch esaa.identity.v1. Presença de autorização exige validação mesmo em história legacy. Bootstrap/register/review autenticados usam verificador Ed25519 já existente, contexto do prefixo validado e nonce. Evento legacy legítimo sem assinatura permanece legacy. Após bootstrap, review requer credencial registrada e escopo exato. Epoch/schema desconhecido ou envelope ambíguo rejeitado antes da normalização. Auth inválida não retorna a qa_role. Claim/complete canônicos e confiança externa NÃO são resolvidos neste patch: 003/002.
