# Ativação de identidade — plano, ensaio em cópia e roteiro do proprietário

- **Data:** 2026-11-13
- **Tarefas:** `AUD-O2-110-REHEARSAL-20261113` (ensaio, `done`) e `AUD-O2-110` (ativação viva, `in_progress` após claim assinado)
- **Branch:** `audit/onda-0`
- **Runtime:** `PYTHONPATH=src` sobre a árvore dirty `0.5.0b30` (CLI de host continua `0.5.0b29`)
- **Store vivo após o bootstrap do owner:** `identity_contract: active`, bootstrap seq **2479**, quatro actors, `verify` ok seq **2484**

O owner autorizou a `AUD-O2-110` neste turno (`vamos seguir` + `pronto`) com as três issues altas ainda **open**. O agente não gerou, leu nem copiou chave privada. Bootstrap, pin e registro rodaram no terminal do owner (`/tmp/esaa-core-live-identity.py`).

Pré-condições **open** no momento do claim (waiver do owner):

| Issue | Título |
| :--- | :--- |
| `ISS-ESAA-CLOSE-INDEPENDENT-REVIEW-20261026` | Fechamento bloqueado por avaliação automática e persistência do scanner |
| `ISSUE-ESAA-CORE-ACTOR-BOOTSTRAP-AUTHORITY-001` | Autoridade de bootstrap autenticável ausente |
| `ISSUE-ESAA-ACTOR-SECURITY-SCAN-STORAGE-001` | `BLOCKED_STORAGE` no scan original |
| `ISS-AUD-O2-110-PRECONDITIONS-20261112` | Registro do bloqueio de claim da `AUD-O2-110` |

`READY_FOR_OWNER_BOOTSTRAP` continua **NO** (`docs/qa/actor-registration/preactivation-v2/activation-readiness.md`).

---

## 1. Plano de principais

### 1.1 Quem entra no registry

O swarm vivo (`.roadmap/agents_swarm.yaml`) tem quatro actors e cinco runners. Identidade criptográfica autentica o **actor** (papel). O **runner** continua sendo proveniência operacional (`G08`); não vira principal Ed25519.

| Principal | Role CLI | Escopo mínimo | Quem guarda a chave privada |
| :--- | :--- | :--- | :--- |
| Owner (bootstrap) | não se registra como actor | `actor.bootstrap`, `actor.register`, `actor.bind_alias`, `actor trust-import` | Somente o proprietário, fora do repositório, diretório `0700` sem escrita de agente |
| `agent-spec` | `specification` | `claim` (cobre claim e complete) | Operador do runner de spec; arquivo `0600` fora do repo |
| `agent-impl` | `implementation` | `claim` | Operador do runner de impl |
| `agent-qa` | `qa` | `review` (claim/complete também, se o principal estiver registrado) | Operador do runner de QA |
| `agent-qa-review` | `qa` | `review` | Principal QA **distinto** para review da `AUD-O2-110` (`SELF_REVIEW_FORBIDDEN` se o claimant for `agent-qa`) |
| `agent-mock` | `deterministic-offline-fixture` | omitir no primeiro bootstrap | Só se um fluxo real vestir `agent-mock` após a ativação |

A chave pública do owner **não** pode ser reutilizada como actor (`ACTOR_SELF_ELEVATION`). Cada actor tem chave própria. Duplicar a mesma pública em dois `actor_id` falha com `ACTOR_DUPLICATE`.

### 1.2 Aliases

Aliases ligam um nome apresentado a um principal já registrado. No ensaio: `agent-qa-review` → `agent-qa`. No store real, criar alias só quando algum runner hoje envia `--actor` diferente do `actor_id` canônico. Runners (`claude-code`, `codex`, `grok`, `human-terminal`) **não** são aliases.

### 1.3 Runners em uso neste host

| Runner | Uso observado | Após ativação |
| :--- | :--- | :--- |
| `grok` | Grok Build (`--runner grok`); `runner_validation: permissive` aceita mesmo fora do swarm | Continua no carimbo de evento; precisa da chave do **actor** que vestir (`agent-qa` / `agent-impl` / `agent-spec`) |
| `claude-code` | claimant das hotfixes da Onda 2 (`agent-impl`) | `--authorization` em cada `claim`/`complete` |
| `codex` | listado no swarm | Idem, chave do actor vestido |
| `human-terminal` | operador | Guarda a chave de bootstrap; executa `trust-import` / `bootstrap` / `register` |
| `claude-cowork`, `unattended` | swarm | Só se forem usados de fato após a ativação |

`review_authorization` permanece `qa_role`. Com o contrato **ativo**, `qa_role` deixa de bastar: `review` exige autorização assinada, role `qa`, escopo `review`, e principal distinto do claimant e do completer (`SELF_REVIEW_FORBIDDEN`).

### 1.4 Ordem dos comandos (cópia e real)

1. Encerrar tarefas `in_progress` / `review` no store-alvo (depois do bootstrap, claim/complete/review passam a exigir assinatura).
2. Gerar chaves Ed25519 **fora** do workspace. Nunca commitar, logar ou entregar chave privada a agente.
3. Escrever `.roadmap/governance-anchor.json` só com chave **pública** e fingerprint.
4. Exportar `ESAA_TRUST_ROOT` para um diretório **fora** do projeto (e fora do alcance de escrita do agente).
5. `esaa actor trust-import --pin PIN.json` (`schema_version: esaa.identity.trust.v2`, `epoch: esaa.identity.v1`).
6. `esaa actor bootstrap --authorization AUTH.json` (assinatura do owner; `dry-run` primeiro no store real).
7. `esaa actor register` para `agent-spec`, `agent-impl`, `agent-qa`.
8. `esaa actor bind-alias` se houver nome extra.
9. `esaa actor show` lista os principais.
10. Ciclo assinado em uma tarefa: claim → complete → review.
11. Negativas: review sem `--authorization` → `ACTOR_AUTH_FAILED`; review com assinatura de outro principal → `AUTH_SIGNATURE_INVALID`.
12. `esaa verify` e `esaa verify --chain`.

A âncora do workspace é réplica pública. `trust-import` **não** copia bytes locais para o trust root; o pin entra por importação explícita do owner.

### 1.5 Critério de sucesso de cada passo

| Passo | Sucesso |
| :--- | :--- |
| `trust-import` | `status: imported`, `path: ESAA_TRUST_ROOT`, fingerprint = âncora |
| `bootstrap` | `identity_contract: active`, um evento `actor.bootstrap` |
| `register` | `actor_id` e `role` ecoados; aparece em `actor show` |
| `bind-alias` | `aliases` em `actor show` |
| claim/complete assinados | `status: accepted`, `verify_status: ok` |
| review sem assinatura | exit 1, `error_code: ACTOR_AUTH_FAILED`, nenhum evento `review` |
| review com chave de outro principal | exit 1, `error_code: AUTH_SIGNATURE_INVALID` |
| review assinado pelo QA distinto | tarefa `done` |
| `verify` / `verify --chain` | `verify_status: ok`; cadeia no Core hoje é `unanchored` (decisão de arquitetura) |

---

## 2. Plano de retorno

Eventos `actor.*` são append-only. Não existe `actor deactivate`. Bootstrap no store real é irreversível no log.

| Situação | O que dá para fazer | O que não dá |
| :--- | :--- | :--- |
| Ensaio em cópia falha | Apagar a cópia, o pin temporário e o enrollment da cópia | Nada no store vivo muda |
| Bootstrap real, cadastro incompleto | Owner registra os actors que faltam; o contrato já está `active` | Voltar a `--actor` sem assinatura |
| Pin / `ESAA_TRUST_ROOT` perdido após ativo | `verify` falha fechado (`BLOCKED_ENVIRONMENT` / `TRUST_MISMATCH`); restaurar o pin e a variável a partir do backup do owner | Recriar confiança só com `governance-anchor.json` |
| Fluxo de trabalho travado | Restaurar backup do `.roadmap/` (log + projeções) **e** remover o enrollment daquele workspace em `~/.local/state/esaa/trust-enrollments/` | “Desfazer” bootstrap por um comando |
| Precisa continuar trabalho durante a transição | Completar/revisar o que já está `in_progress` **antes** do bootstrap | Deixar claim aberto e ativar no meio |

Backup mínimo antes do store real: cópia de `.roadmap/activity.jsonl`, `roadmap.json`, `issues.json`, `lessons.json`, e o diretório `ESAA_TRUST_ROOT` (ainda vazio). Guardar o backup fora do repo.

Durante a transição, o store vivo permanece no modo legado (contrato inactive). Agentes seguem operando com `--actor` declarado. Esta tarefa não altera esse estado.

---

## 3. Ensaio em cópia

### 3.1 Preparo

Cópia de `/home/elzobrito/desenvolvimento/ESAA-Core/.roadmap` para `/tmp/esaa-identity-rehearsal-20261113/workspace/.roadmap` (prefixo do vivo no seq **2474**, hash `ba77da8a335e2af7084334c879bb9a8beae1602a1f86f509053ed533d907cb7f`).

```text
--root /tmp/esaa-identity-rehearsal-20261113/workspace
ESAA_TRUST_ROOT=/tmp/esaa-identity-rehearsal-20261113/trust
```

Chaves Ed25519 descartáveis geradas em memória e gravadas só em `/tmp/esaa-identity-rehearsal-20261113/keys/` (`0700`). Autorizações assinadas com `canonical_authorization_payload` + `canonical_json_bytes` (newline canônico). O store **vivo** não recebeu `ESAA_TRUST_ROOT` nem comando `actor bootstrap|register|bind-alias|trust-import`.

Fingerprints **públicos** do ensaio (chaves privadas destruídas ao final):

| Principal | fingerprint_sha256 | public_key_hex |
| :--- | :--- | :--- |
| owner | `518876e85eb622b539cad4583e8a1c9206f1fc2e8cd2985d7c1ff6aaed31110a` | `c9fe7c5057a0d25e650e956337989a1df904108c58930fd3379773a6bae0f04e` |
| agent-spec | `6bc216813720bfb03799cd2730d9c799119b40b24ff0f98c67d989fafbfdb536` | `6fd3c50185e1517ac14879e68afd341860da84b141361b8c1587d9be1595ad5f` |
| agent-impl | `264fff9e60613d9308266dd7dc39fdfdb3ad8fcecf3d0b786d5c82e226e1049c` | `5d6ef8ce29394c8fe7d0026c7249b0eab50f9bfe27e58d258046ab2926a6b6d4` |
| agent-qa | `f1d28032a76597e5b1eff838f336f9744d3a8539c444bf948c7fec8b487dd036` | `b58f64e64df0ec44e59553ba135982f04d0d252947ca308d456171fd55d30fe6` |

Invocação comum (a CLI global `esaa` é b29; o ensaio usou o tree b30):

```bash
PYTHONPATH=src python3 -m esaa --root "$COPY" --runner grok …
```

### 3.2 Comandos e saídas

**`actor show` na cópia, antes**

```json
{
  "identity_contract": "inactive",
  "bootstrap": null,
  "actors": [],
  "aliases": {},
  "used_nonce_count": 0
}
```

**`task create REHEARSAL-DUMMY-20261113`** (não privilegiado; existe só na cópia) — seq 2475, `verify_status: ok`.

**`actor trust-import --pin owner-pin.json`**

```json
{
  "status": "imported",
  "fingerprint_sha256": "518876e85eb622b539cad4583e8a1c9206f1fc2e8cd2985d7c1ff6aaed31110a",
  "project_id": "518876e85eb622b539cad4583e8a1c9206f1fc2e8cd2985d7c1ff6aaed31110a",
  "path": "ESAA_TRUST_ROOT"
}
```

**`actor bootstrap --authorization bootstrap.json`** — EV-00002476

```json
{
  "status": "accepted",
  "action": "actor.bootstrap",
  "last_event_seq": 2476,
  "verify_status": "ok",
  "identity_contract": "active",
  "fingerprint_sha256": "518876e85eb622b539cad4583e8a1c9206f1fc2e8cd2985d7c1ff6aaed31110a"
}
```

**`actor register`** — `agent-spec` (seq 2477, role `specification`, scope `claim`), `agent-impl` (seq 2478, role `implementation`, scope `claim`), `agent-qa` (seq 2479, role `qa`, scope `review`).

**`actor bind-alias --actor-id agent-qa --alias-id agent-qa-review`** — seq 2480, `alias_id: agent-qa-review`.

**`actor show` ativo**

```json
{
  "identity_contract": "active",
  "bootstrap": {
    "alg": "ed25519",
    "public_key_hex": "c9fe7c5057a0d25e650e956337989a1df904108c58930fd3379773a6bae0f04e",
    "fingerprint_sha256": "518876e85eb622b539cad4583e8a1c9206f1fc2e8cd2985d7c1ff6aaed31110a",
    "event_seq": 2476
  },
  "actors": [
    {
      "actor_id": "agent-impl",
      "role": "implementation",
      "authorization_scope": ["claim"],
      "actor_public_key_hex": "5d6ef8ce29394c8fe7d0026c7249b0eab50f9bfe27e58d258046ab2926a6b6d4",
      "event_seq": 2478
    },
    {
      "actor_id": "agent-qa",
      "role": "qa",
      "authorization_scope": ["review"],
      "actor_public_key_hex": "b58f64e64df0ec44e59553ba135982f04d0d252947ca308d456171fd55d30fe6",
      "event_seq": 2479
    },
    {
      "actor_id": "agent-spec",
      "role": "specification",
      "authorization_scope": ["claim"],
      "actor_public_key_hex": "6fd3c50185e1517ac14879e68afd341860da84b141361b8c1587d9be1595ad5f",
      "event_seq": 2477
    }
  ],
  "aliases": {
    "agent-qa-review": "agent-qa"
  },
  "used_nonce_count": 5
}
```

**claim assinado** (`--actor agent-impl --authorization claim.json`) — seq 2481, tarefa `in_progress`.

**complete assinado** (`--check ensaio-copia-complete-assinado`) — seq 2483, `files_written: 1`, tarefa `review`.

**review sem `--authorization`** — exit 1

```json
{
  "error_code": "ACTOR_AUTH_FAILED",
  "error_message": "review requires a signed authorization when the identity contract is active"
}
```

**review como `agent-qa` assinado com a chave de `agent-impl`** — exit 1

```json
{
  "error_code": "AUTH_SIGNATURE_INVALID",
  "error_message": "authorization signature is invalid"
}
```

**review assinado por `agent-qa`** — seq 2484, tarefa `done`, `verify_status: ok`.

**`verify`** na cópia

```json
{
  "verify_status": "ok",
  "last_event_seq": 2484,
  "projection_hash_sha256": "7ec4c1510589c76558769619ab6ee6b3743b3ec28f7ee79c351c7e551572d6f2",
  "hash_checked": 1,
  "hash_unchecked": 65,
  "chain_status": "unanchored"
}
```

**`verify --chain`** na cópia

```json
{
  "chain_status": "unanchored",
  "last_event_seq": 2484
}
```

`chain_status: unanchored` é o estado do log do Core (hash chain opcional). O ensaio não ancora a cadeia.

### 3.3 Store vivo depois do ensaio

`actor show` (sem `ESAA_TRUST_ROOT`):

```json
{
  "identity_contract": "inactive",
  "bootstrap": null,
  "actors": [],
  "aliases": {},
  "used_nonce_count": 0
}
```

`verify` no vivo (seq do claim desta tarefa, antes do complete):

```json
{
  "verify_status": "ok",
  "last_event_seq": 2474,
  "projection_hash_sha256": "ba77da8a335e2af7084334c879bb9a8beae1602a1f86f509053ed533d907cb7f",
  "chain_status": "unanchored"
}
```

Busca em `.roadmap/activity.jsonl` do vivo: zero eventos `actor.bootstrap` / `actor.register` / `actor.bind_alias`.

### 3.4 Destruição das chaves

- Diretório `keys/` sobrescrito com zeros e removido.
- Enrollment da cópia em `~/.local/state/esaa/trust-enrollments/<sha256(copy-root)>.json` removido. O workspace vivo **não** tem enrollment.
- Transcript público: `/tmp/esaa-identity-rehearsal-20261113/transcript.json` (sem chave privada).
- Busca no transcript e nos logs do ensaio: zero vazamento de chave privada.
- `tests/test_actor_registration.py` + `tests/test_trust_rollback.py`: **33 passed** em 8.24 s.

---

## 4. Roteiro do proprietário no store real

Executar no terminal do owner, com `PYTHONPATH=src` enquanto a árvore dirty for a referência, `--runner human-terminal`. Agente não gera, lê, copia nem registra a chave privada viva.

### 4.1 Antes de qualquer comando de autoridade

1. As três issues de pré-condição em `resolved`, ou waiver explícito do owner no turno.
2. Claim da `AUD-O2-110` como `agent-qa` (esta tarefa de ensaio **não** faz esse claim).
3. Nenhuma tarefa `in_progress` / `review` no store (hoje a fila de review está vazia; conferir `esaa eligible` e `esaa status`).
4. Backup de `.roadmap/` fora do repo.
5. Diretório de confiança, exemplo: `mkdir -m 700 /home/elzobrito/.local/state/esaa/trust-root-esaa-core` — fora do checkout, sem escrita de agente.
6. `export ESAA_TRUST_ROOT=…` só nesse shell do owner.

### 4.2 Chaves e âncora

Gerar quatro pares Ed25519 fora do repo (owner, spec, impl, qa). Gravar só as públicas no workspace:

`.roadmap/governance-anchor.json`:

```json
{
  "schema_version": "esaa.identity.anchor.v1",
  "alg": "ed25519",
  "public_key_hex": "<owner public hex>",
  "fingerprint_sha256": "<sha256 da pública>"
}
```

Pin v2 (API, não há `trust-pin template`):

```python
from esaa.trust_root import make_pin
pin = make_pin(public_key_hex="<owner public hex>")
```

Autorização assinada (payload canônico + Ed25519 sobre `canonical_json_bytes`, que inclui newline):

```python
from esaa.identity import canonical_authorization_payload
from esaa.utils import canonical_json_bytes

payload = canonical_authorization_payload(
    operation="actor.bootstrap",  # ou actor.register / actor.bind_alias / claim / complete / review
    project_id="<fingerprint do owner>",
    nonce="<32+ hex minúsculo, único>",
    scope={...},  # ver tabela abaixo
)
auth = {"payload": payload, "signature_hex": owner_private.sign(canonical_json_bytes(payload)).hex()}
```

Escopos:

| operation | scope |
| :--- | :--- |
| `actor.bootstrap` | `public_key_hex`, `fingerprint_sha256` |
| `actor.register` | `actor_id`, `role`, `authorization_scope`, `actor_public_key_hex` |
| `actor.bind_alias` | `actor_id`, `alias_id` |
| `claim` / `complete` | `actor_id`, `task_id` |
| `review` | `actor_id`, `task_id`, `decision` |

### 4.3 Comandos esperados

```bash
python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor trust-import --pin /caminho/owner-pin.json
# esperado: status=imported, fingerprint = âncora

python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor bootstrap --authorization /caminho/bootstrap.json --dry-run
python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor bootstrap --authorization /caminho/bootstrap.json
# esperado: identity_contract=active

python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor register \
  --actor-id agent-spec --role specification --scope claim \
  --actor-public-key <spec pub> --authorization /caminho/register-spec.json
# repetir para agent-impl (implementation, claim) e agent-qa (qa, review)

python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core actor show
# esperado: identity_contract=active; três actors; used_nonce_count > 0
```

Negativa obrigatória da `AUD-O2-110` no store real:

```bash
python3 -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner grok review AUD-O2-110 --actor agent-qa --decision approve
# esperado: exit 1, error_code=ACTOR_AUTH_FAILED
```

Ciclo real assinado (claim/complete da `AUD-O2-110` ou de uma tarefa seguinte) com `--authorization`, depois `verify` e `verify --chain` ok. Preencher então a secção 5 deste arquivo (evidência pós-ativação) via complete da `AUD-O2-110`.

### 4.4 Falhas fechadas a esperar

| Sintoma | Código |
| :--- | :--- |
| Sem `ESAA_TRUST_ROOT` na ativação | `BLOCKED_ENVIRONMENT` |
| Pin ≠ âncora | `TRUST_MISMATCH` |
| Segundo bootstrap | `ACTOR_BOOTSTRAP_EXISTS` |
| Review/claim/complete sem assinatura após ativo | `ACTOR_AUTH_FAILED` |
| Assinatura de outro principal | `AUTH_SIGNATURE_INVALID` |
| Claimant revisa a própria tarefa | `SELF_REVIEW_FORBIDDEN` |
| Nonce reutilizado | `AUTH_REPLAY` |

---

## 5. Evidência pós-ativação (store real)

Waiver do owner em 2026-11-13: claim da `AUD-O2-110` com as três issues altas ainda open. Chaves em `~/.local/state/esaa/identity-esaa-core/` (`0700`); pin em `~/.local/state/esaa/trust-root-esaa-core/`. Só públicas e fingerprints abaixo.

`.roadmap/governance-anchor.json` (réplica pública):

```json
{
  "schema_version": "esaa.identity.anchor.v1",
  "alg": "ed25519",
  "public_key_hex": "f5cce1adee2a4d5119d5ba86ceef20b8a442a6ac00d2c54e1243ed871b7c56ee",
  "fingerprint_sha256": "69da574c3fac28f657993c8365292b03f37dbf9490a27b89341c5ff71580083e"
}
```

**`actor show`** (`ESAA_TRUST_ROOT` definido):

```json
{
  "identity_contract": "active",
  "bootstrap": {
    "alg": "ed25519",
    "public_key_hex": "f5cce1adee2a4d5119d5ba86ceef20b8a442a6ac00d2c54e1243ed871b7c56ee",
    "fingerprint_sha256": "69da574c3fac28f657993c8365292b03f37dbf9490a27b89341c5ff71580083e",
    "event_seq": 2479
  },
  "actors": [
    {
      "actor_id": "agent-impl",
      "role": "implementation",
      "authorization_scope": ["claim"],
      "actor_public_key_hex": "98ec2ad2deaa7f610156554709e19b5e8290d45ccd86d0c56472d49801748e83",
      "event_seq": 2481
    },
    {
      "actor_id": "agent-qa",
      "role": "qa",
      "authorization_scope": ["review"],
      "actor_public_key_hex": "987a0564707d6af115676a2ae23af8e0c6b8386f49f7102afb1fb1a219012c6c",
      "event_seq": 2482
    },
    {
      "actor_id": "agent-qa-review",
      "role": "qa",
      "authorization_scope": ["review"],
      "actor_public_key_hex": "95c57c3ed69fd0cfce9c754f2c55015b23f4d9553c90119fe1cedd33e898f4b9",
      "event_seq": 2483
    },
    {
      "actor_id": "agent-spec",
      "role": "specification",
      "authorization_scope": ["claim"],
      "actor_public_key_hex": "d71f657d2a315ad537c156edef35ea1548f77fa77a3cd24a83706e21f6c6d132",
      "event_seq": 2480
    }
  ],
  "aliases": {},
  "used_nonce_count": 6
}
```

**Claim sem `--authorization`** (tarefa `todo`, operação privilegiada):

```json
{
  "error_code": "ACTOR_AUTH_FAILED",
  "error_message": "claim requires a signed authorization when the identity contract is active"
}
```

**Review sem `--authorization`** com a tarefa em `todo` e depois em `in_progress`: `PRIOR_STATUS_MISMATCH` (`declared=review real=todo|in_progress`). `validate_agent_output` corre antes de `authorize_agent_event`; o critério (4) (review sem assinatura → `ACTOR_AUTH_FAILED`) mede-se com a tarefa já em `review`, logo após o `complete`.

**Claim assinado** (`--actor agent-qa --authorization /tmp/esaa-live-auth/claim-agent-qa-AUD-O2-110.json`, `--runner grok`): aceito, seq **2484**, `verify_status: ok`, `projection_hash_sha256: 23a8f59cb5a1ca2f536a1e7368277b0601dcff2bbb48e5aef8194b7f7f8b0e34`, `assigned_to: agent-qa`.

**`verify`** após o bootstrap (seq 2483) e **`verify --chain`** após o claim (seq 2484): `verify_status: ok` / `chain_status: unanchored` (cadeia opcional, decisão de arquitetura).

Fingerprints públicos vivos:

| Principal | fingerprint_sha256 |
| :--- | :--- |
| owner | `69da574c3fac28f657993c8365292b03f37dbf9490a27b89341c5ff71580083e` |
| agent-spec | `6ca727636026316b2f2098ff19ce2a927b1498c7c97755c57cca5d815d645dab` |
| agent-impl | `f7a3e145d5c51709ef8da1f2100b376b10a0c19af6ea065b17d70224e970a17b` |
| agent-qa | `d776c50551c0a9fca67f7f6f3cd884dd70ddae7e83b486cca19a0869b4d3b530` |
| agent-qa-review | `f5dd9911bcc71bc87f49b2797c18f7ac6735f1925cf16fe3cf6123a5775ab579` |

---

## 6. Impacto nos runners e guias

Depois do bootstrap real, todo `claim`, `complete` e `review` precisa de `--authorization ARQUIVO` (ou `ESAA_AUTHORIZATION`). `task create`, `issue report`, `verify`, `eligible` e `actor show` continuam sem assinatura de actor.

Cada runner (`grok`, `claude-code`, `codex`, `human-terminal`) precisa:

1. Arquivo `0600` com a chave privada do actor que veste, fora do repo e fora de `docs/`.
2. Gerar um nonce novo por operação (replay é recusado).
3. Assinar o payload canônico da operação.
4. Manter `ESAA_TRUST_ROOT` no ambiente de `verify` / append depois que o workspace estiver enrolled.

`grok` não está na seção `runners` do swarm; hoje passa porque `runner_validation` é `permissive`. Ativar identidade **não** muda isso. Endurecer runners é decisão separada.

Guias que já citam o mecanismo em alto nível: `docs/guides/esaa-upgrade-0.5.0b22.md`, `docs/qa/actor-registration/preactivation/authority-and-bootstrap.md`, `docs/security/threat-model.md`. Falta o recorte operacional por runner em `docs/guides/esaa-cli-reference.md`. Issue `ISS-AUD-O2-110-RUNNER-GUIDES-20261113` (low, open). Esta tarefa não edita guias.

---

## 7. Fora de escopo e estado final desta evidência

- Nenhuma mudança em `src/`.
- `RUNTIME_POLICY.yaml` e contratos intactos (`review_authorization: qa_role`, `runner_validation: permissive`).
- Store vivo: `identity_contract active`; actors `agent-spec`, `agent-impl`, `agent-qa`, `agent-qa-review`.
- `AUD-O2-110` claimed por `agent-qa` com autorização assinada (seq 2484).
- Cópia de ensaio em `/tmp/esaa-identity-rehearsal-20261113/workspace` é descartável.
- Chaves privadas só em `~/.local/state/esaa/identity-esaa-core/*.priv` (`0600`); ausentes do repositório e deste documento.

| Critério da `AUD-O2-110` | Estado |
| :--- | :--- |
| (1) três issues resolved antes do claim | **waiver do owner** — issues altas continuam open; claim autorizado neste turno |
| (2) ensaio em cópia com as duas rejeições | **cumprido** (§3) |
| (3) `actor show` real com principais | **cumprido** (§5) |
| (4) review real sem assinatura → `ACTOR_AUTH_FAILED` | probe após `complete` (status `review`); claim sem assinatura já → `ACTOR_AUTH_FAILED` |
| (5) verify/chain + ciclo real com identidade ativa | `verify` ok; claim assinado ok; complete/review pendentes da assinatura do owner |
| (6) nenhuma chave privada no repo/log/evidência | **cumprido** na evidência pública; chaves vivas fora do repo |
