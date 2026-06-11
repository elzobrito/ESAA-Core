-- =============================================================================
--  Configuração do SSO all-in-one (Hub Sistemas CPS) — tabela `configuracoes`
-- -----------------------------------------------------------------------------
--  Fonte de contrato: SsoAllIn-portugues-estruturado.md (§4 e §10).
--  Este script é idempotente para a tabela usada no OE:
--      configuracoes(parametro, valor, status, created_at)
--
--  Estratégia padrão:
--    1. remover somente os parâmetros SSO conhecidos;
--    2. inserir novamente os valores oficiais do sistema cliente.
--
--  Essa abordagem evita quebrar em bancos onde não existe índice único em
--  `parametro` e evita executar `ALTER TABLE` em produção.
--
--  Marcadores para substituir antes de aplicar:
--    Os valores podem vir de .roadmap/sso-client-input.local.json durante o G0.
--    __SSO_CLIENT_ID__       -> client_id cadastrado no Hub para este sistema.
--    __SSO_CLIENT_SECRET__   -> client_secret entregue pelo Hub para este sistema.
--    __CLIENT_BASE_URL__     -> URL pública base do sistema. Pode incluir o base path,
--                               ex.: https://oe.cps.sp.gov.br/oe.
--    __CLIENT_BASE_PATH__    -> subcaminho separado, ex.: /oe. Use vazio quando
--                               CLIENT_BASE_URL já incluir o subcaminho.
--
--  Valores que mudam obrigatoriamente por sistema:
--    SSO_CLIENT_ID, SSO_CLIENT_SECRET e CLIENT_BASE_URL.
--    CLIENT_BASE_PATH só deve ser preenchido quando o sistema usar subcaminho
--    separado da URL pública.
--
--  Observação importante:
--    O Atrio atual pode retornar o JWT no campo access_token. A classe
--    SsoClientAllInOne.php aceita isso por padrão interno; não crie parâmetro
--    extra no banco para essa compatibilidade.
-- =============================================================================

START TRANSACTION;

DELETE FROM `configuracoes`
WHERE `parametro` IN (
    'HUB_BASE_URL',
    'SSO_AUTHZ_ENDPOINT',
    'SSO_TOKEN_ENDPOINT',
    'SSO_JWKS_ENDPOINT',
    'SSO_HUB_ISSUER',
    'SSO_CLIENT_ID',
    'SSO_CLIENT_SECRET',
    'CLIENT_BASE_URL',
    'CLIENT_BASE_PATH',
    'SSO_CALLBACK_PATH',
    'SSO_SCOPE',
    'SSO_FLOW_MODES',
    'SSO_POST_LOGIN_REDIRECT',
    'SSO_POST_LOGOUT_REDIRECT',
    'SSO_STATE_TTL_SECONDS',
    'SSO_JWKS_TTL_SECONDS',
    'SSO_SESSION_ABSOLUTE_TTL_SECONDS',
    'SSO_JWT_SKEW_SECONDS'
);

INSERT INTO `configuracoes` (`parametro`, `valor`, `status`, `created_at`) VALUES
    -- URL base do Hub. Os endpoints abaixo usam o mesmo domínio do Atrio.
    ('HUB_BASE_URL', 'https://atrio.cps.sp.gov.br', '1', NOW()),
    -- Endpoint de autorização: usado pelo navegador ao iniciar o login.
    ('SSO_AUTHZ_ENDPOINT', 'https://atrio.cps.sp.gov.br/sso/authorize', '1', NOW()),
    -- Endpoint de token: troca backend do code por JWT.
    ('SSO_TOKEN_ENDPOINT', 'https://atrio.cps.sp.gov.br/sso/token', '1', NOW()),
    -- Endpoint JWKS: chaves públicas para validar a assinatura do JWT.
    ('SSO_JWKS_ENDPOINT', 'https://atrio.cps.sp.gov.br/.well-known/jwks.json', '1', NOW()),
    -- Emissor esperado no claim iss do JWT.
    ('SSO_HUB_ISSUER', 'https://atrio.cps.sp.gov.br', '1', NOW()),

    -- Credenciais exclusivas do sistema cliente cadastrado no Hub.
    ('SSO_CLIENT_ID', '__SSO_CLIENT_ID__', '1', NOW()),
    ('SSO_CLIENT_SECRET', '__SSO_CLIENT_SECRET__', '1', NOW()),

    -- Base pública do sistema cliente e composição da redirect_uri.
    ('CLIENT_BASE_URL', '__CLIENT_BASE_URL__', '1', NOW()),
    ('CLIENT_BASE_PATH', '__CLIENT_BASE_PATH__', '1', NOW()),
    ('SSO_CALLBACK_PATH', '/sso/callback', '1', NOW()),

    -- Escopos solicitados ao Hub.
    ('SSO_SCOPE', 'openid profile email', '1', NOW()),
    -- Modos aceitos. Use "client_initiated,hub_initiated" quando o portal do Hub iniciar o fluxo.
    ('SSO_FLOW_MODES', 'client_initiated', '1', NOW()),
    -- Destino local depois do login SSO concluído.
    ('SSO_POST_LOGIN_REDIRECT', '/home', '1', NOW()),
    -- Destino local depois do logout.
    ('SSO_POST_LOGOUT_REDIRECT', '/', '1', NOW()),
    -- Validade do state anti-CSRF, em segundos.
    ('SSO_STATE_TTL_SECONDS', '600', '1', NOW()),
    -- TTL do cache JWKS, em segundos.
    ('SSO_JWKS_TTL_SECONDS', '86400', '1', NOW()),
    -- TTL absoluto da sessão local pós-SSO, em segundos.
    ('SSO_SESSION_ABSOLUTE_TTL_SECONDS', '28800', '1', NOW()),
    -- Tolerância de relógio na validação do JWT, em segundos.
    ('SSO_JWT_SKEW_SECONDS', '60', '1', NOW());

COMMIT;

-- =============================================================================
--  Alternativa quando G0 confirmar índice único em `parametro`:
--  o agente pode gerar INSERT ... ON DUPLICATE KEY UPDATE em vez de DELETE+INSERT.
--  Não use essa alternativa sem confirmar o índice, para evitar duplicidade.
-- =============================================================================
