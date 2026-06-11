# Classe `SsoAllIn` em Português Estruturado — Contrato Normativo Único

> **Autoridade:** este documento é a **fonte única de verdade** do cliente SSO all-in-one.
> Qualquer implementação (PHP, Go, Python, C#, Genexus ou outra) é uma **tradução derivada**
> deste contrato. **Se uma implementação divergir deste `.md`, a implementação é que deve ser
> corrigida — o contrato não perde autoridade.**
>
> **Idioma:** todos os comentários, docblocks, mensagens documentais, comentários de SQL e textos
> de apoio gerados a partir deste contrato **DEVEM** estar em português do Brasil (pt-BR).
>
> **Versão do contrato:** `SSOALLIN-CONTRATO-2026-05-30`

---

## 1. Escopo e não-escopo

**No escopo (o que o cliente all-in-one faz):**
- Início do login (client-initiated, com `state` + PKCE + `nonce`).
- Recebimento do callback (client-initiated e hub-initiated).
- Troca backend do `code` por token (`grant_type=authorization_code`).
- Validação completa do JWT (assinatura RS256/ES256 via JWKS, `iss`, `aud`, `exp`, `nbf`, `iat`, `nonce`, `jti`).
- Anti-replay de `jti` persistente e atômico.
- Extração e validação do CPF (formato + dígitos verificadores).
- Sessão SSO minimizada + **`loginLocal(cpf)`** (único ponto de customização do sistema cliente).
- `health` operator-safe, `logout` protegido, auditoria redigida, minimização de dados (LGPD).

**Fora do escopo (declarado explicitamente):** descoberta autônoma via `/.well-known` + manifest do
Hub, preflight/cadastro do cliente no Hub, rate-limiting e rotação de `client_secret`. O cliente
all-in-one lê endpoints da **configuração** (banco → ambiente → padrão). Esses itens, quando
necessários, são responsabilidade de camadas externas.

---

## 2. Catálogo de requisitos `AIO-xxx` (rastreabilidade ESAA)

Os `targets` do roadmap apontam para estes códigos. Cada um é normativo e verificável.

| Código | Requisito | Onde no contrato | Verificação |
|---|---|---|---|
| AIO-001 | Discovery detecta linguagem, framework, roteador, build/autoload, sessão, login legado, tabela/campo de CPF, banco e base path | §11 (discovery) | runtime-contract.json preenchido |
| AIO-002 | `runtime-contract.json` contém `language_profile`, `config_table` e `sso_file_plan` | §11 | schema valida |
| AIO-003 | `runtime://sso_file_plan.*` resolve para destinos reais (nunca genéricos) | §11 | cobertura 100% |
| AIO-004 | Campos P0 não omitidos; sem detecção ⇒ ler `.roadmap/sso-client-input.local.json` e, se ainda faltar dado, `manual_input_required=true`; textos pt-BR | §11 | QA textual |
| AIO-010 | API pública: `health`, `startLogin`, `handleCallback`, `logout`, `getCurrentUser`, `loginLocal(cpf)` | §9 | lint/compilação |
| AIO-011 | `loginLocal(cpf)` é o **único** ponto de customização e recebe **apenas** o CPF confiável | §6, §9 | assinatura |
| AIO-012 | Configuração resolvida na ordem banco → ambiente → padrão | §4, §9 `configValue` | testes |
| AIO-013 | Artefato compila/linta e tem comentários em pt-BR | §9 | QA textual |
| AIO-020 | SQL idempotente com todos os `PARAMETROS_OBRIGATORIOS` | §4, §10 | testes |
| AIO-021 | Comentários SQL em pt-BR; placeholders para `SSO_CLIENT_ID`/`SSO_CLIENT_SECRET` | §10 | QA textual |
| AIO-022 | Estratégia idempotente por banco (MySQL: `ON DUPLICATE KEY UPDATE` ou `DELETE`+`INSERT`) | §10 | testes |
| AIO-030 | `state` aleatório, com hash, uso único e TTL; `flow_modes` respeitados | §5, §9 | testes |
| AIO-031 | Token exchange backend com `grant_type=authorization_code` + PKCE (`code_verifier`); aceita JWT em `id_token` ou, por compatibilidade Atrio, em `access_token` | §9 `trocarCodePorToken` | testes |
| AIO-032 | Validação JWT RS256/ES256 via JWKS, cache JWKS, refresh único por `kid` | §7, §9, Apêndice A | testes |
| AIO-033 | Anti-replay de `jti` **persistente e atômico** entre requisições/processos | §7, §9 | testes concorrência |
| AIO-034 | Minimização + auditoria redigida + `health` operator-safe + `logout` protegido + regeneração de id de sessão | §8, §9 | testes |
| AIO-040 | Controller chama `startLogin`, `handleCallback`, `health`, `logout` e traduz retornos neutros | §12 | testes |
| AIO-041 | Rotas equivalentes de SSO; em PHP/Olivia: `/sso/launch`, `/sso/callback`, `/health/sso` e logout quando aplicável | §12 | smoke HTTP |
| AIO-042 | Sem lógica de JWT/exchange fora do cliente; sem segredo hardcoded | §12 | revisão |
| AIO-050 | `loginLocal(cpf)` recebe só o CPF confiável e é chamado **por último** | §6 | testes |
| AIO-051 | `loginLocal(cpf)` reproduz o login legado (sessão/permissões do sistema) | §6 | testes |
| AIO-052 | `loginLocal(cpf)` é **conclusivo e fail-closed**: autentica+redireciona OU nega+finaliza | §6 | testes |
| AIO-060 | Certificação cobre SQL, cliente, rotas, login local, segurança e LGPD | §13 | certificação |
| AIO-061 | Sem vazamento de segredo/PII em sessão, log ou auditoria | §8 | varredura |
| AIO-062 | Comentários/docblocks/SQL em pt-BR, sem marcadores comuns em inglês | §13 | QA textual |

---

## 3. Atributos e dependências

```text
ATRIBUTOS
    configuracoes        // opções explícitas + leitor de banco (config_table)
    sessao               // sessão do sistema cliente
    armazenamentoEstado  // store do state (ver §7)
    armazenamentoJti     // store anti-replay do jti (persistente e atômico, ver §7)
    cacheJwks            // cache do JWKS com TTL (ver §7)
    auditoria            // sink de auditoria redigida
    relogio              // fonte de tempo (now)
    transporteHttp       // cliente HTTP backend (injetável; default nativo)
```

---

## 4. Configuração: `PARAMETROS_OBRIGATORIOS`, aliases e ordem de resolução

**Ordem de resolução (sempre):** `config_table` (banco) → variável de ambiente → valor padrão.
A leitura de banco usa um leitor injetável (`config_value`) que **não pode lançar**: erro de banco
cai silenciosamente para ambiente/padrão.

```text
CONSTANTE ALIAS_CONFIGURACAO
    hub_base_url                 -> [HUB_BASE_URL]
    authorization_endpoint       -> [SSO_AUTHZ_ENDPOINT, SSO_AUTHORIZATION_ENDPOINT]
    token_endpoint               -> [SSO_TOKEN_ENDPOINT]
    jwks_endpoint                -> [SSO_JWKS_ENDPOINT, SSO_JWKS_URI]
    issuer                       -> [SSO_HUB_ISSUER, HUB_SSO_ISSUER]
    client_id                    -> [SSO_CLIENT_ID]
    client_secret                -> [SSO_CLIENT_SECRET]
    client_base_url              -> [CLIENT_PUBLIC_ORIGIN, CLIENT_BASE_URL]
    client_base_path             -> [CLIENT_BASE_PATH]
    callback_path                -> [SSO_CALLBACK_PATH]
    scope                        -> [SSO_SCOPE]
    post_login_redirect          -> [SSO_POST_LOGIN_REDIRECT]
    post_logout_redirect         -> [SSO_POST_LOGOUT_REDIRECT]
    state_ttl_seconds            -> [SSO_STATE_TTL_SECONDS]
    jwks_ttl_seconds             -> [SSO_JWKS_TTL_SECONDS]
    session_absolute_ttl_seconds -> [SSO_SESSION_ABSOLUTE_TTL_SECONDS]
    clock_skew_seconds           -> [SSO_JWT_SKEW_SECONDS]
    flow_modes                   -> [SSO_FLOW_MODES]
```

```text
CONSTANTE PARAMETROS_OBRIGATORIOS
    // mínimos para login SSO; ausência => health degradado (503) e startLogin nega.
    SSO_CLIENT_ID
    SSO_CLIENT_SECRET
    SSO_AUTHZ_ENDPOINT           // ou HUB_BASE_URL (deriva /sso/authorize)
    SSO_TOKEN_ENDPOINT           // ou HUB_BASE_URL (deriva /sso/token)
    SSO_JWKS_ENDPOINT            // ou HUB_BASE_URL (deriva /.well-known/jwks.json)
    SSO_HUB_ISSUER               // ou HUB_BASE_URL
    CLIENT_BASE_URL              // origem pública do cliente
    SSO_CALLBACK_PATH            // default /sso/callback

CONSTANTE PARAMETROS_OPCIONAIS_COM_PADRAO
    CLIENT_BASE_PATH=""  SSO_SCOPE="openid profile email"
    SSO_STATE_TTL_SECONDS=600  SSO_JWKS_TTL_SECONDS=86400
    SSO_SESSION_ABSOLUTE_TTL_SECONDS=28800  SSO_JWT_SKEW_SECONDS=60
    SSO_POST_LOGIN_REDIRECT="/"  SSO_POST_LOGOUT_REDIRECT="/"
    SSO_FLOW_MODES="client_initiated"   // padrão seguro; hub_initiated é opt-in explícito

CONSTANTE PARAMETROS_SIGILOSOS  // nunca em sessão/log/auditoria em claro
    client_secret  code  access_token  id_token  jwt  state  nonce  cpf
```

Compatibilidade do token do Atrio: o cliente prioriza `id_token` quando o Hub o retorna. Quando
`id_token` não vem no JSON, a classe aceita o JWT no campo `access_token` por padrão interno, porque
esse é o formato emitido pelo Atrio atual. Essa compatibilidade **não** é parâmetro obrigatório de
banco e **não** deve aumentar o script SQL padrão dos sistemas clientes.

---

## 5. `flow_modes` (modos de fluxo)

`flow_modes` declara os modos aceitos: `client_initiated`, `hub_initiated` ou ambos.
O **padrão, quando não configurado, é apenas `client_initiated`** (mais seguro); `hub_initiated`
deve ser habilitado **explicitamente** em `flow_modes`, pois callback sem `state` aumenta o risco
de CSRF/troca de sessão e só é apropriado quando o próprio Hub inicia o fluxo.

- **client_initiated:** `state` é **obrigatório**. O cliente gera `state`/`nonce`/PKCE em `startLogin`,
  persiste server-side e **valida no callback**. `state` ausente, divergente, expirado ou reusado
  **aborta** o fluxo.
- **hub_initiated:** o portal do Hub inicia o login; o callback chega com `code` e **sem `state`
  local pendente**. É aceito **somente** quando `hub_initiated` está em `flow_modes` e **não há**
  `state` pendente na sessão. A proteção anti-CSRF vem do `code` de uso único + troca backend.
- **Regra anti-ambiguidade:** se existir `state` pendente na sessão e o callback chegar **sem**
`state`, **negar** (`callback_state_missing`) — não tratar como hub-initiated.

---

## 6. Contrato de `loginLocal(cpf)` — método finalizador, conclusivo e fail-closed

`loginLocal(cpf)` é o **único** método que o desenvolvedor do sistema cliente implementa. Ele é
**finalizador**: além de logar localmente, **encerra a resposta** (redireciona ou nega).

**Regras normativas (AIO-011, AIO-050, AIO-051, AIO-052):**
1. Recebe **apenas** o CPF confiável (11 dígitos, já validado por JWT/JWKS/anti-replay). Nenhum outro parâmetro.
2. Busca o usuário local pelo CPF (com fallback opcional para CPF histórico de 9 dígitos, quando o sistema usar).
3. Carrega perfil e permissões locais conforme o sistema cliente.
4. Cria a sessão local conforme o sistema cliente (ex.: chaves consumidas pelos middlewares legados).
5. Em **sucesso**: **redireciona** para a área logada (retorna a resposta de redirecionamento).
6. Quando o CPF **não existir** ou **não tiver perfil local**: **nega** o acesso e **finaliza** a resposta (retorna a resposta de negação).
7. **Não pode ficar vazio em produção.** A implementação base retorna **negação fail-closed** (`login_local_nao_implementado`, 503) até ser implementada.
8. Se `loginLocal(cpf)` retornar **sem** ser conclusivo (não autenticou, não redirecionou e não negou), o `handleCallback` trata como **erro interno seguro** (`erro_interno_login_local`, 503).
9. Não deve depender de métodos legados que a classe all-in-one não possui. Ao reaproveitar código antigo, adapte somente a busca do usuário, a carga de permissões e a montagem da sessão local; finalize com `redirecionar(...)` ou `negar(...)` da própria classe.

> **Resultado conclusivo** = a chamada produz uma **resposta** terminal: ou `redirecionar(area_logada)`
> ou `negar(motivo, http)`. Qualquer outro retorno (vazio/nulo/indefinido) é **inconclusivo** e
> vira erro interno seguro. O contrato **não** exige booleano; exige **conclusividade fail-closed**.

A ordem é fixa e **fail-closed**: o framework valida tudo e chama `loginLocal(cpf)` **primeiro**.
**Somente em sucesso conclusivo** (redirecionamento) o framework regenera o id de sessão e registra
a **sessão SSO minimizada**. Em **negação conclusiva** ou retorno **inconclusivo**, o framework
**limpa todo o estado SSO** (`sso`, `sso_state`, `usuario_local`) — nenhuma sessão SSO autenticada
pode permanecer quando o acesso é negado. Além disso, `handleCallback` é envolvido em **try/catch
geral**: qualquer falha inesperada vira `erro_interno_sso` (503) com o estado SSO limpo.

---

## 7. Stores padrão (state, jti, jwks)

- **armazenamentoEstado (state):** server-side, chave = `hashSeguro(state)`, **uso único** (consumir remove), TTL = `state_ttl_seconds`. Backing default: sessão do servidor. Guarda `state_hash`, `nonce`, `nonce_hash`, `code_verifier`, `urlCallback`, `criadoEm`, `expiraEm`.
- **armazenamentoJti (anti-replay):** **DEVE ser persistente e atômico entre requisições e processos.** Backing default: **arquivo com lock exclusivo** (ex.: `flock LOCK_EX`) **ou** tabela de banco com índice único em `jti_hash`. Chave = `hashSeguro(jti)`, valor = `exp`; expurga expirados. Indisponibilidade do store ⇒ **`jti_store_indisponivel`** (nega; não confunde com replay). Nunca usar store apenas em memória de processo.
- **cacheJwks (JWKS):** cache com TTL = `jwks_ttl_seconds` (≤ 24h). Refresh **único** quando aparece `kid` desconhecido, antes de rejeitar. Backing default: arquivo/cache **com escrita atômica (arquivo temporário + `rename`)** para evitar cache truncado sob concorrência.
- **Diretório de storage (default):** quando `storage_dir` não é informado, derivar um diretório **isolado por cliente** a partir de `hash(client_id + issuer)` — evita colisão de `jti`/JWKS entre múltiplos sistemas no mesmo host. Em produção, prefira um `storage_dir` explícito e persistente por sistema.

---

## 8. Propriedades de segurança (obrigatórias)

- `state` aleatório (CSPRNG ≥ 256 bits), com hash em store, uso único e TTL; `nonce` e **PKCE S256**.
- Troca de `code` **somente backend**, `grant_type=authorization_code`, `client_secret` no corpo `application/x-www-form-urlencoded`, `code_verifier` no corpo. `redirect_uri` **idêntico** em `startLogin`, callback e troca.
- Endpoints (`authorization`/`token`/`jwks`) exigem **HTTPS** (salvo `allow_insecure_http=true` para teste) e **rejeitam** query string no `token_endpoint`.
- JWT: `alg` ∈ `{RS256, ES256}` (rejeitar `none`/HS*), assinatura via JWKS, `iss`, `aud` (contém `client_id`), `exp` (skew ≤ 60s), `nbf`, `iat` (quando presente), `nonce` (quando presente), `jti` (anti-replay).
- CPF: extrair de `cpf`/`sub=cpf:NNN`/`preferred_username`/`documento`; **validar dígitos verificadores** e rejeitar sequências repetidas.
- **Minimização:** na sessão SSO só ficam **hashes** (`sso.cpf_hash`, `sso.subject_hash`) e metadados; **nunca** JWT cru, `code`, `client_secret`, `state`, `nonce` ou CPF completo.
- **Auditoria redigida:** todo evento passa por `redigirDadosSensiveis` (chaves sigilosas → `[redigido]`, CPF → mascarado, JWT → `[jwt_redigido]`); preservar campos operacionais (`reason_code`, `correlacao`).
- `health` **operator-safe**: nunca lança; reporta prontidão/dependências sem expor segredos.
- `logout` protegido: exige **POST** + **CSRF**.
- **Regeneração do id de sessão** após login bem-sucedido e após logout (anti session-fixation).
- **`handleCallback` é envolvido em try/catch geral**: qualquer `Throwable` (transporte, auditoria, OpenSSL, filesystem, `loginLocal`) é contido e vira `erro_interno_sso` (503), limpando o estado SSO.
- **O sink de auditoria nunca derruba o fluxo**: falha no callback de auditoria é capturada e cai para log redigido.
- **Sessão SSO autenticada só é criada após sucesso conclusivo de `loginLocal`**; negação/erro limpam `sso`/`sso_state`/`usuario_local`.
- **Allowlist do callback** aceita e ignora parâmetros OIDC conhecidos (`iss`, `session_state`) e é configurável (`callback_allowed_params`).

---

## 9. A classe em português estruturado (normativo)

```text
CLASSE SsoAllIn

    MÉTODO construtor(opcoes)
        inicializar configuracoes, sessao, transporteHttp
        inicializar armazenamentoEstado, armazenamentoJti (persistente/atomico), cacheJwks
        inicializar auditoria redigida e relogio
    FIMMÉTODO


    MÉTODO configValue(chave, valorPadrao)
        PARA CADA alias EM aliasesDaConfiguracao(chave) FAÇA
            valor <- lerConfiguracaoNoBanco(alias)            // não pode lançar; erro => ignora
            SE valor existir E não estiver vazio ENTÃO RETORNAR valor FIMSE
        FIMPARA
        PARA CADA alias EM aliasesDaConfiguracao(chave) FAÇA
            valor <- lerVariavelDeAmbiente(alias)
            SE valor existir E não estiver vazio ENTÃO RETORNAR valor FIMSE
        FIMPARA
        RETORNAR valorPadrao
    FIMMÉTODO


    MÉTODO health()                                            // operator-safe: NUNCA lança
        TENTAR
            resultado.status <- "ok"; resultado.configuracoes <- {}; resultado.dependencias <- {}
            PARA CADA p EM PARAMETROS_OBRIGATORIOS FAÇA
                resultado.configuracoes[p] <- (configValue(p, vazio) não está vazio)
            FIMPARA
            resultado.dependencias.authorization_endpoint <- urlSeguraOuAusente(authorizationEndpoint())
            resultado.dependencias.token_endpoint         <- urlSeguraOuAusente(tokenEndpoint())
            resultado.dependencias.jwks_endpoint          <- urlSeguraOuAusente(jwksEndpoint())
            resultado.dependencias.jwks_alcancavel        <- jwksAlcancavel()    // GET com timeout, em try
            resultado.dependencias.storage_jti            <- armazenamentoJtiDisponivel()
            SE alguma config obrigatória ausente OU alguma dependência indisponível ENTÃO
                resultado.status <- "degraded"; resultado.codigoHttp <- 503
            SENÃO resultado.codigoHttp <- 200 FIMSE
            registrarAuditoria("sso_health_verificado", resultado sem dados sensíveis)
            RETORNAR resultado
        CAPTURAR erro
            registrarAuditoria("sso_health_degradado", erro redigido)
            RETORNAR respostaHealthDegradado("erro_interno_health", 503)
        FIMTENTAR
    FIMMÉTODO


    MÉTODO startLogin()
        TENTAR
            clientId <- configValue("SSO_CLIENT_ID", vazio)
            endpointAutorizacao <- authorizationEndpoint()
            urlCallback <- montarCallbackUrl()
            escopo <- configValue("SSO_SCOPE", "openid profile email")

            SE clientId estiver vazio ENTÃO RETORNAR negar("client_id_nao_configurado", 503) FIMSE
            SE endpointAutorizacao não for HTTPS segura ENTÃO RETORNAR negar("authorization_endpoint_invalido", 503) FIMSE
            SE urlCallback não for HTTPS segura ENTÃO RETORNAR negar("callback_url_invalida", 503) FIMSE

            state <- gerarValorAleatorioSeguro()
            nonce <- gerarValorAleatorioSeguro()
            codigoVerificador <- gerarValorAleatorioSeguro()
            desafioPkce <- gerarDesafioPkce(codigoVerificador)   // S256

            salvarStateTemporario(state, nonce, codigoVerificador, urlCallback, dataHoraAtual(), ttlState())

            urlAutorizacao <- montarUrlComParametros(endpointAutorizacao, {
                "response_type":"code", "client_id":clientId, "redirect_uri":urlCallback,
                "scope":escopo, "state":state, "nonce":nonce,
                "code_challenge":desafioPkce, "code_challenge_method":"S256"
            })
            registrarAuditoria("sso_login_iniciado", {"client_id":clientId, "redirect_uri":urlCallback, "scope":escopo})
            RETORNAR redirecionar(urlAutorizacao)
        CAPTURAR erro
            registrarAuditoria("sso_login_inicio_falhou", erro redigido)
            RETORNAR negar("erro_interno_start_login", 503)
        FIMTENTAR
    FIMMÉTODO


    MÉTODO handleCallback(requisicao)
        TENTAR
            SE requisicao.parametro("error") não estiver vazio ENTÃO
                registrarAuditoria("sso_callback_negado_pelo_hub", erro redigido)
                RETORNAR negar("hub_negou_autenticacao", 401)
            FIMSE

            code  <- requisicao.parametro("code")
            state <- requisicao.parametro("state")
            SE code estiver vazio ENTÃO RETORNAR negar("codigo_ausente", 400) FIMSE

            haStatePendente <- armazenamentoEstado.existePendente()

            // ----- flow_modes (§5) -----
            SE state estiver vazio ENTÃO
                SE (NÃO haStatePendente) E flowModeAllows("hub_initiated") ENTÃO
                    dadosState <- {urlCallback: montarCallbackUrl(), nonce: vazio, codigoVerificador: vazio}
                SENÃO
                    RETORNAR negar("state_ausente", 400)
                FIMSE
            SENÃO
                SE NÃO haStatePendente ENTÃO RETORNAR negar("state_desconhecido", 401) FIMSE
                dadosState <- consumirState(state)            // uso único
                SE dadosState não existir ENTÃO RETORNAR negar("state_invalido", 401) FIMSE
                SE dadosState expirado ENTÃO RETORNAR negar("state_expirado", 401) FIMSE
                SE dadosState.state_hash != hashSeguro(state) ENTÃO RETORNAR negar("state_divergente", 401) FIMSE
                SE dadosState.urlCallback != montarCallbackUrl() ENTÃO RETORNAR negar("redirect_uri_divergente", 401) FIMSE
            FIMSE

            respostaToken <- trocarCodePorToken(code, dadosState.codigoVerificador, dadosState.urlCallback)
            SE respostaToken for inválida ENTÃO RETORNAR negar("troca_token_falhou", 401) FIMSE

            jwt <- selecionarJwtConfiavel(respostaToken)       // prioriza id_token; aceita access_token do Atrio por padrão interno
            SE jwt estiver vazio ENTÃO RETORNAR negar("jwt_ausente", 401) FIMSE

            jwks <- carregarJwks()
            claims <- validarJwt(jwt, jwks)                    // assinatura (§7, Apêndice A)
            SE validarIssuer(claims) falhar      ENTÃO RETORNAR negar("jwt_issuer_invalido", 401) FIMSE
            SE validarAudience(claims) falhar    ENTÃO RETORNAR negar("jwt_audience_invalido", 401) FIMSE
            SE validarExpiracao(claims) falhar   ENTÃO RETORNAR negar("jwt_expirado", 401) FIMSE
            SE validarIssuedAtSePresente(claims) falhar ENTÃO RETORNAR negar("jwt_iat_futuro", 401) FIMSE
            SE validarNonceSePresente(claims, dadosState.nonce) falhar ENTÃO RETORNAR negar("nonce_invalido", 401) FIMSE
            SE validarJtiContraReplay(claims) falhar ENTÃO RETORNAR negar(motivoDoJti, 401) FIMSE

            cpf <- extrairCpfConfiavel(claims)
            SE cpf estiver vazio ENTÃO RETORNAR negar("cpf_ausente", 401) FIMSE
            SE NÃO cpfFormatoValido(cpf) ENTÃO RETORNAR negar("cpf_invalido", 401) FIMSE
            SE NÃO cpfDigitosVerificadoresValidos(cpf) ENTÃO RETORNAR negar("cpf_dv_invalido", 401) FIMSE

            registrarAuditoria("sso_jwt_validado", {"issuer":claims.iss, "subject_hash":hashSeguro(claims.sub)})

            // ----- finalizador local PRIMEIRO (§6), fail-closed -----
            resultadoLocal <- loginLocal(cpf)
            SE NÃO respostaConclusiva(resultadoLocal) ENTÃO
                limparEstadoSso()                              // remove sso, sso_state, usuario_local
                registrarAuditoria("sso_login_local_inconclusivo", {"cpf_mascarado": mascararCpf(cpf)})
                RETORNAR negar("erro_interno_login_local", 503)
            FIMSE
            SE resultadoLocal for negação ENTÃO
                limparEstadoSso()                              // negado: nenhuma sessão SSO autenticada permanece
                RETORNAR resultadoLocal
            FIMSE

            // sucesso conclusivo: só agora registrar a sessão SSO e regenerar o id
            regenerarIdDaSessao()
            registrarSessaoSsoMinimizada(claims, cpf)
            registrarAuditoria("sso_login_concluido", {"issuer":claims.iss, "subject_hash":hashSeguro(claims.sub)})
            RETORNAR resultadoLocal
        CAPTURAR erro
            registrarAuditoria("sso_callback_erro", erro redigido)
            RETORNAR negar("erro_interno_sso", 503)
        FIMTENTAR
    FIMMÉTODO


    MÉTODO logout(requisicao)
        TENTAR
            SE logoutExigePost() E requisicao.metodo != "POST" ENTÃO RETORNAR negar("logout_metodo_invalido", 405) FIMSE
            SE logoutExigeCsrf() E csrfInvalido(requisicao) ENTÃO RETORNAR negar("logout_csrf_invalido", 403) FIMSE
            limparSessaoSso(); limparSessaoLocal(); regenerarIdDaSessao()
            registrarAuditoria("sso_logout_concluido", vazio)
            RETORNAR redirecionar(configValue("SSO_POST_LOGOUT_REDIRECT", "/"))
        CAPTURAR erro
            registrarAuditoria("sso_logout_erro", erro redigido)
            RETORNAR negar("erro_interno_logout", 503)
        FIMTENTAR
    FIMMÉTODO


    MÉTODO getCurrentUser()
        SE sessao.obter("sso.autenticado") não for verdadeiro ENTÃO RETORNAR vazio FIMSE
        SE sessao.obter("sso.expira_em") < timestampAtual() ENTÃO RETORNAR vazio FIMSE
        usuarioLocal <- sessao.obter("usuario_local")          // preenchido por loginLocal
        u <- {}
        u.id <- usuarioLocal.id se existir
        u.nome <- usuarioLocal.nome se existir
        u.perfis <- usuarioLocal.perfis se existir
        u.permissoes <- usuarioLocal.permissoes se existir
        u.autenticadoPorSso <- verdadeiro
        RETORNAR u
    FIMMÉTODO


    MÉTODO loginLocal(cpf)
        /*
        PONTO ÚNICO DE CUSTOMIZAÇÃO DO SISTEMA CLIENTE (§6).

        Recebe apenas o CPF confiável (validado por JWT/JWKS/anti-replay).
        DEVE: buscar usuário local pelo CPF; carregar perfil/permissões; criar a sessão local;
        em sucesso REDIRECIONAR para a área logada; sem perfil NEGAR e finalizar.
        É um método FINALIZADOR e CONCLUSIVO (fail-closed). NÃO pode ficar vazio em produção.

        Implementação base: negação fail-closed até ser implementada.
        Para OE/PHP: preencher $_SESSION["usuario_local"] e permissões conforme AuthController::logar_usuario.
        */
        RETORNAR negar("login_local_nao_implementado", 503)
    FIMMÉTODO


    // ---------- Endpoints e URLs ----------
    MÉTODO authorizationEndpoint()
        e <- configValue("SSO_AUTHZ_ENDPOINT", vazio)
        SE e vazio ENTÃO e <- concatenarUrl(configValue("HUB_BASE_URL", vazio), "/sso/authorize") FIMSE
        validarUrlHttps(e); RETORNAR e
    FIMMÉTODO
    MÉTODO tokenEndpoint()
        e <- configValue("SSO_TOKEN_ENDPOINT", vazio)
        SE e vazio ENTÃO e <- concatenarUrl(configValue("HUB_BASE_URL", vazio), "/sso/token") FIMSE
        validarUrlHttps(e); RETORNAR e
    FIMMÉTODO
    MÉTODO jwksEndpoint()
        e <- configValue("SSO_JWKS_ENDPOINT", vazio)
        SE e vazio ENTÃO e <- concatenarUrl(configValue("HUB_BASE_URL", vazio), "/.well-known/jwks.json") FIMSE
        validarUrlHttps(e); RETORNAR e
    FIMMÉTODO
    MÉTODO montarCallbackUrl()
        // origem + base path (idempotente, sem duplicar) + callback path
        origem <- configValue("CLIENT_BASE_URL", vazio)
        basePath <- normalizarBasePath(configValue("CLIENT_BASE_PATH", ""))
        callbackPath <- "/" + semBarras(configValue("SSO_CALLBACK_PATH", "/sso/callback"))
        RETORNAR concatenarSemDuplicar(origem, basePath) + callbackPath
    FIMMÉTODO


    // ---------- Token, JWKS, JWT ----------
    MÉTODO trocarCodePorToken(code, codigoVerificador, urlCallback)
        endpoint <- tokenEndpoint()
        SE endpoint contiver "?" ENTÃO RETORNAR respostaInvalida("token_endpoint_com_query") FIMSE
        clientId <- configValue("SSO_CLIENT_ID", vazio); clientSecret <- configValue("SSO_CLIENT_SECRET", vazio)
        SE clientId vazio OU clientSecret vazio ENTÃO RETORNAR respostaInvalida("credencial_cliente_ausente") FIMSE
        corpo <- formUrlEncoded({
            "grant_type":"authorization_code", "client_id":clientId, "client_secret":clientSecret,
            "code":code, "redirect_uri":urlCallback, "code_verifier":codigoVerificador
        })
        respostaHttp <- enviarPostBackend(endpoint, corpo)     // Content-Type form-urlencoded
        SE respostaHttp.codigo não estiver entre 200 e 299 ENTÃO
            registrarAuditoria("sso_token_exchange_falhou", respostaHttp sem corpo sensível)
            RETORNAR respostaInvalida("token_endpoint_recusou")
        FIMSE
        corpoJson <- interpretarJson(respostaHttp.corpo)
        SE corpoJson.id_token existir ENTÃO RETORNAR {id_token: corpoJson.id_token} FIMSE
        SE corpoJson.access_token existir ENTÃO
            // Compatibilidade padrão com Atrio: o JWT do cliente vem no access_token.
            RETORNAR {id_token: corpoJson.access_token}
        FIMSE
        RETORNAR respostaInvalida("token_endpoint_recusou")
    FIMMÉTODO

    MÉTODO carregarJwks()
        cacheado <- cacheJwks.obter("jwks")
        SE cacheado existir E não expirado ENTÃO RETORNAR cacheado FIMSE
        respostaHttp <- enviarGetBackend(jwksEndpoint())
        SE respostaHttp.codigo não estiver entre 200 e 299 ENTÃO RETORNAR erro("jwks_indisponivel") FIMSE
        jwks <- interpretarJson(respostaHttp.corpo); validarFormatoJwks(jwks)
        cacheJwks.salvar("jwks", jwks, ttlJwks()); RETORNAR jwks
    FIMMÉTODO

    MÉTODO validarJwt(jwt, jwks)
        partes <- dividirJwt(jwt)
        SE partes não tiverem header, payload e assinatura ENTÃO RETORNAR erro("jwt_formato_invalido") FIMSE
        header <- decodificarJsonBase64Url(partes.header); claims <- decodificarJsonBase64Url(partes.payload)
        SE header.alg não estiver em algoritmosPermitidos() ENTÃO RETORNAR erro("jwt_algoritmo_nao_permitido") FIMSE
        SE header.kid estiver vazio ENTÃO RETORNAR erro("jwt_kid_ausente") FIMSE
        chave <- encontrarChavePorKid(jwks, header.kid)
        SE chave não existir ENTÃO
            jwks2 <- carregarJwksForcandoAtualizacao(); chave <- encontrarChavePorKid(jwks2, header.kid)
        FIMSE
        SE chave não existir ENTÃO RETORNAR erro("jwt_chave_nao_encontrada") FIMSE
        SE NÃO verificarAssinaturaJwt(partes, chave, header.alg) ENTÃO RETORNAR erro("jwt_assinatura_invalida") FIMSE
        RETORNAR claims
    FIMMÉTODO

    // validarIssuer / validarAudience / validarExpiracao / validarIssuedAtSePresente /
    // validarNonceSePresente / validarJtiContraReplay: ver versão anterior do contrato
    // (mantidas; jti usa armazenamentoJti persistente/atomico e distingue "jti_store_indisponivel").

    MÉTODO extrairCpfConfiavel(claims)
        cpf <- primeiroValorNaoVazio(claims.cpf, claims.documento,
                                     claims.preferred_username se formato CPF, claims.sub se formato cpf:NNN)
        cpf <- manterSomenteDigitos(cpf)
        SE cpf não tiver 11 dígitos ENTÃO RETORNAR vazio FIMSE
        RETORNAR cpf
    FIMMÉTODO

    MÉTODO cpfDigitosVerificadoresValidos(cpf)
        SE cpf for sequência repetida (todos iguais) ENTÃO RETORNAR falso FIMSE
        PARA digito DE 9 ATÉ 10 FAÇA
            soma <- 0
            PARA i DE 0 ATÉ digito-1 FAÇA soma <- soma + inteiro(cpf[i]) * ((digito+1)-i) FIMPARA
            esperado <- (soma*10) MOD 11; SE esperado = 10 ENTÃO esperado <- 0 FIMSE
            SE inteiro(cpf[digito]) != esperado ENTÃO RETORNAR falso FIMSE
        FIMPARA
        RETORNAR verdadeiro
    FIMMÉTODO

    MÉTODO registrarSessaoSsoMinimizada(claims, cpf)
        sessao.definir("sso.autenticado", verdadeiro)
        sessao.definir("sso.issuer", claims.iss)
        sessao.definir("sso.subject_hash", hashSeguro(claims.sub))
        sessao.definir("sso.cpf_hash", hashSeguro(cpf))
        sessao.definir("sso.jti_hash", hashSeguro(claims.jti))
        sessao.definir("sso.autenticado_em", dataHoraAtual())
        sessao.definir("sso.expira_em", timestampAtual() + sessionAbsoluteTtl())
        PARA CADA s EM ["access_token","id_token","jwt","client_secret","code","state","nonce"] FAÇA removerDaSessao(s) FIMPARA
    FIMMÉTODO

    // salvarStateTemporario / consumirState / negar / registrarAuditoria / redigirDadosSensiveis /
    // aliasesDaConfiguracao / ttlState / ttlJwks / algoritmosPermitidos / logoutExigePost /
    // logoutExigeCsrf: ver versão anterior (mantidas).
    // respostaConclusiva(r): RETORNAR (r é uma resposta de redirecionamento OU de negação).

FIMCLASSE
```

---

## 10. SQL de configuração (resumo normativo)

Gerar script **idempotente** em `runtime://sso_file_plan.config_sql` com **todos** os
`PARAMETROS_OBRIGATORIOS` + opcionais reconhecidos pelo SQL padrão, **comentários SQL em pt-BR**, placeholders para
`SSO_CLIENT_ID`/`SSO_CLIENT_SECRET` (sem segredo real em claro), valores padrão do Hub CPS e os
valores do cliente derivados de `CLIENT_BASE_URL`+`CLIENT_BASE_PATH`+`SSO_CALLBACK_PATH`.
MySQL: usar `DELETE` dos parâmetros conhecidos seguido de `INSERT` dentro de transação como padrão
compatível com tabelas sem índice único; `INSERT ... ON DUPLICATE KEY UPDATE` é alternativa quando
G0 confirmar índice único em `parametro`. O SQL padrão não cria parâmetro para compatibilidade
`access_token` do Atrio, pois ela é comportamento interno da classe.

---

## 11. Discovery (G0) — o que materializar

`runtime-contract.json` DEVE conter `language_profile`, `config_table` e `sso_file_plan` com:
`all_in_one_client`, `config_sql`, `controller`, `routes`, `tests`, `docs` — todos resolvidos para
**caminhos reais** do sistema. Perfis: `php`→`SsoClientAllInOne.php`; `python`→`sso_client_all_in_one.py`;
`go`→`sso_client_all_in_one.go`; `csharp`→`SsoClientAllInOne.cs`; `genexus`→procedure/objeto HTTP (ver §Apêndice B).
Campos não detectados ⇒ `manual_input_required=true` (nunca omitir em silêncio).

### 11.1 Entrada local opcional do rollout

Antes de marcar `manual_input_required`, G0 DEVE procurar `.roadmap/sso-client-input.local.json`
na raiz do sistema cliente. Esse arquivo complementa a descoberta com dados que normalmente não
estão no código-fonte, como credenciais e URLs públicas do cliente SSO. Ele **não** substitui a
descoberta da stack, roteador, sessão, login legado, banco ou caminhos reais.

Campos reconhecidos:

```json
{
  "system_name": "Nome do Sistema",
  "system_slug": "sigla-do-sistema",
  "language_profile": "php",
  "client_base_url": "https://sistema.cps.sp.gov.br/sistema",
  "client_base_path": "",
  "sso_callback_path": "/sso/callback",
  "post_login_redirect": "/home",
  "post_logout_redirect": "/",
  "sso_client_id": "<client_id_do_sistema>",
  "sso_client_secret": "<client_secret_do_sistema>",
  "flow_modes": "client_initiated"
}
```

Regras:
- O arquivo local é entrada de geração, não fonte de configuração em runtime.
- `sso_client_id`, `sso_client_secret` e `client_base_url` alimentam o SQL gerado.
- `language_profile` só pode confirmar ou preencher ausência; se contrariar a stack detectada, G0
  deve registrar conflito e exigir decisão manual.
- Segredo real não deve ser versionado. O arquivo local deve ficar no `.gitignore`; o repositório
  pode versionar apenas `.roadmap/templates/sso-client-input.local.example.json`.

---

## Apêndice A — Criptografia por linguagem (assinatura JWT)

**Regra:** usar uma biblioteca JWT/JWKS validada **ou** implementar a verificação conforme o algoritmo abaixo.

| Linguagem | Biblioteca recomendada | Sem biblioteca |
|---|---|---|
| PHP | `firebase/php-jwt` (+ `web-token/jwt-*` p/ JWKS) | `openssl_verify` + conversão JWK→PEM (abaixo) |
| Python | `pyjwt[crypto]` ou `python-jose` (`jwt.PyJWKClient`) | `cryptography` + verificação manual |
| Go | `github.com/golang-jwt/jwt/v5` + `github.com/lestrrat-go/jwx/v2/jwk` | `crypto/rsa`, `crypto/ecdsa` |
| C#/.NET | `Microsoft.IdentityModel.Tokens` + `System.IdentityModel.Tokens.Jwt` | `RSA`/`ECDsa` do framework |
| Genexus | objeto externo/microserviço (ver Apêndice B) | não recomendado |

**Algoritmo lib-less (quando não há biblioteca, ex.: PHP):**
- **JWK RSA → PEM:** `n`,`e` (base64url) → `INTEGER`+`INTEGER` → `SEQUENCE` → `SubjectPublicKeyInfo` (OID `rsaEncryption`) → PEM `PUBLIC KEY`.
- **JWK EC P-256 → PEM:** ponto não comprimido `0x04 || x || y` (65 bytes) → `SubjectPublicKeyInfo` (OIDs `id-ecPublicKey` + `prime256v1`) → PEM `PUBLIC KEY`.
- **ES256:** a assinatura JOSE é `r || s` (64 bytes); converter para DER `SEQUENCE(INTEGER r, INTEGER s)` antes de `verify` SHA-256.
- **RS256:** `verify` direto SHA-256 sobre `header.payload`.
(O código de referência ASN.1 em PHP — `asn1Integer/Sequence/Oid/Length`, `joseToDerEs256`, `rsaJwkToPem`, `ecJwkToPem` — é o exemplo canônico desta conversão.)

---

## Apêndice B — Genexus (tratamento especial)

Genexus (4GL low-code) **não** deve reimplementar ASN.1/verificação de assinatura/lock de `jti`.
Padrão recomendado: **(a)** publicar o cliente all-in-one como **microserviço** (PHP/Go/C#) que o
Genexus consome por HTTPS, mantendo o **mesmo contrato lógico**; ou **(b)** encapsular a parte
criptográfica em **External Object/.NET/Java** e implementar em Genexus apenas `startLogin`,
`handleCallback` (orquestração), `loginLocal(cpf)` e o store de `jti` em tabela com índice único.
A regra `loginLocal(cpf)` finalizador e fail-closed (§6) é idêntica.

---

## 12. Wiring HTTP (G4)

Duas formas equivalentes de expor o cliente por HTTP:

**A) Controller separado** — chama os métodos neutros (`startLogin`, `handleCallback`, `health`,
`logout`) e traduz `{status, headers, body}` para a resposta nativa.

**B) All-in-one (recomendado para hosts estilo `Controller#metodo`)** — a própria classe expõe os
métodos de entrada HTTP, que lêem `$_SESSION`/`$_GET` e emitem a resposta nativa, delegando aos
métodos neutros:

| Rota | Método de entrada | Método neutro |
|---|---|---|
| `GET /health/sso{:param}` | `health_sso` | `health()` |
| `GET /sso/launch{:param}` | `launch` | `startLogin($_SESSION)` |
| `GET /sso/callback{:param}` | `callback` | `handleCallback($_SESSION, $_GET)` |

Exemplo (OliviaRouter):

```php
$router->get('/health/sso{:param}', 'SsoClientAllInOne#health_sso');
$router->get('/sso/launch{:param}',  'SsoClientAllInOne#launch');
$router->get('/sso/callback{:param}', 'SsoClientAllInOne#callback');
```

Requisitos do adaptador HTTP:
- O controller DEVE ser instanciável pelo roteador **sem argumentos**; a configuração é resolvida
  via `config_value` (banco) → ambiente → padrão. Em hosts Olivia/OE, o leitor da tabela
  `configuracoes` é detectado automaticamente.
- Para roteadores que resolvem `Controller#metodo` em namespace/diretório fixos (ex.: Olivia →
  `app/Controller`, namespace `OliviaApp\Controller`), o arquivo DEVE declarar esse namespace e
  residir no diretório de controllers. A classe é namespace-safe (usa `\` nos tipos globais).
- A resposta de `loginLocal(cpf)` é **conclusiva**: redirecionamento (`Location`), negação
  (`ok=false`) ou sucesso já renderizado (`ok=true`, view emitida); o emissor não reemite saída
  já enviada.
- **Nenhuma** lógica de JWT/exchange fora do cliente; **nenhum** segredo hardcoded.

## 13. Certificação (G6) — checklist

Aprovar somente se: SQL contém todos os parâmetros oficiais (pt-BR, idempotente) e não cria
configuração desnecessária para a compatibilidade `access_token`; cliente compila/linta;
rotas respondem; login válido cria sessão e `loginLocal(cpf)` redireciona; falhas de `state`, `code`,
JWT, JWKS, replay de `jti`, CPF/DV e Hub-error são **negadas**; token em `id_token` e token em
`access_token` do Atrio são aceitos conforme o contrato; `loginLocal` inconclusivo vira erro
interno 503; segredos/CPF completo/JWT cru **não** vazam em sessão/log/auditoria; `health` é
operator-safe; `logout` exige POST+CSRF; id de sessão é regenerado; **todos** os comentários/docblocks
e comentários SQL estão em pt-BR (sem marcadores comuns em inglês).
