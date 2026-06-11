# Plano de Correção — esaa-core

> **Origem:** auditoria read-only de 2026-06-09 (código, contratos, event store, 218 testes executados).
> **Roadmap executável:** `.roadmap/roadmap.correction-plan.template.json` (21 tasks, 7 tríades spec→impl→qa, validado contra `roadmap.schema.json` v0.4.1).
> **Princípio:** cada correção preserva o invariante central do ESAA — replay determinístico e hash de projeção estável. Toda mudança de comportamento exige golden test de replay.

---

## 1. Inventário de requisitos de correção

### Segurança

| ID | Problema | Risco |
|----|----------|-------|
| SEC-01 | Event store sem tamper-evidence (JSONL puro, sem hash chain ou assinatura); edição manual reescreve a história sem detecção | **Crítico** |
| SEC-02 | Identidade de actor autodeclarada; prefixo `agent-qa*` concede role `qa` sem registro — `review(approve)` forjável | **Crítico** |
| SEC-03 | `_reviewer_role` persistido no payload e confiado no replay (`projector.py:137`) — forjável via edição do store | **Alto** |
| SEC-04 | Lockfile sem detecção de stale (pid gravado mas nunca verificado); crash → deadlock permanente | **Alto** |
| SEC-05 | External effects aceitam `target_root` absoluto arbitrário vindo do input do plugin; sem allowlist de roots | **Alto** |
| SEC-06 | Sem limites de tamanho em `file_updates` nem na resposta do `HttpLlmAdapter` — exaustão de disco/memória | **Médio** |

### Arquitetura

| ID | Problema | Risco |
|----|----------|-------|
| ARC-01 | `service.py` com 2.798 linhas — god class acumulando 10+ responsabilidades | **Alto** (manutenibilidade) |
| ARC-02 | Submit faz parse completo do store + 4–6 `materialize()` por ação; snapshots existem mas não são usados no caminho quente | **Alto** (escala) |
| ARC-03 | `STALE_STATE_*` sem política de retry definida — responsabilidade implícita do chamador | **Médio** |
| ARC-04 | `verify.start/ok` auto-atestados pelo mesmo writer, 3 eventos de overhead por ação do agente | **Médio** |
| ARC-05 | Três implementações divergentes de path-safety (validator, file_effects, external_effects) | **Médio** (drift) |

### Qualidade e higiene

| ID | Problema |
|----|----------|
| QUA-01 | Mojibake em `file_effects.py`, formatação degenerada em `service.py`; sem ruff/black/mypy |
| QUA-02 | Drift de versão: docs/contratos 0.4.1 × pyproject 0.5.0b5 × dist 0.5.0b4 |
| QUA-03 | `.gitignore` com typo (`./roadmap/` ≠ `.roadmap/`), `dist/` não ignorado, `__pycache__` na árvore |
| QUA-04 | Assets de cliente real (SSO/CPS) dentro do `.roadmap/` do framework |
| QUA-05 | Scripts one-off em `src/audit/` convivendo com o pacote distribuível |
| QUA-06 | Sem CI (lint/type/teste); `requires-python >=3.11` não validado em matriz |

---

## 2. Estrutura do roadmap (7 grupos, 21 tasks)

```
G01 Higiene, tooling e CI            T-001..003   (QUA-01..06)        ← fundação
 ├─► G02 Integridade do event store  T-004..006   (SEC-01, SEC-03)
 │    ├─► G03 Identidade de actors   T-007..009   (SEC-02)
 │    └─► G07 Performance/projeção   T-019..021   (ARC-02, ARC-04)
 ├─► G04 Concorrência (locks/retry)  T-010..012   (SEC-04, ARC-03)
 │    └─► G06 Refatoração do service T-016..018   (ARC-01, ARC-05)
 │         └─► G07 (também depende de G06)
 └─► G05 Sandbox external effects    T-013..015   (SEC-05, SEC-06)
```

Racional da ordem:

1. **G01 primeiro** — CI + lint são o gate que protege todo o resto. Sem isso, as correções de segurança podem regredir silenciosamente. São também os itens de menor risco e maior retorno imediato (quick wins).
2. **G02 antes de G03** — a revalidação de role no replay (SEC-03) só tem valor probatório se o store for tamper-evident (SEC-01). Hash chain é o alicerce forense.
3. **G04 e G05 em paralelo** — independentes entre si; ambos dependem só da fundação.
4. **G06 depois de G04** — refatorar `service.py` enquanto se mexe no retry/lock do mesmo arquivo geraria conflito; serializar evita retrabalho.
5. **G07 por último** — otimização sobre módulos já decompostos (G06) e com cadeia de hash já definida (G02), pois snapshot+tail precisa validar a cadeia a partir do manifest.

---

## 3. Fases e prioridades

### Fase 0 — Quick wins (G01) · P0 · esforço baixo

Correções mecânicas e tooling. Critério de saída: CI verde obrigatório, versão única, repositório limpo de mojibake/artefatos, assets de cliente extraídos.

Riscos: nenhum técnico relevante. A formatação em massa (black/ruff) deve ser um commit isolado para não poluir diffs futuros.

### Fase 1 — Núcleo de segurança (G02 → G03) · P0 · esforço médio-alto

- **Hash chain (SEC-01):** `prev_event_hash` + `event_hash` por evento; `parse_event_store` valida a cadeia (fail-closed, `CHAIN_BROKEN`); `verify --chain` para auditoria independente; `chain init` migra stores legados.
- **Reviewer role (SEC-03):** sai do payload do agente; o Orchestrator grava em campo próprio do evento e o projector **revalida** contra `agents_swarm.yaml` no replay.
- **Identidade (SEC-02):** registro obrigatório no swarm em modo `identity.strict` (novo default), remoção do fallback por prefixo, HMAC opcional por actor, threat model documentado.

Riscos: migração de stores legados — mitigado por golden test (replay pré/pós-migração com hash idêntico) e modo de compatibilidade com warning.

### Fase 2 — Robustez operacional (G04 ∥ G05) · P1 · esforço médio

- **Locks (SEC-04):** pid+timestamp+hostname no lockfile, liveness check, takeover de lock órfão após `lock_max_age`.
- **Retry (ARC-03):** backoff exponencial limitado em `submit` para `STALE_STATE_*`, com revalidação do output contra o estado novo; `max_retries` em `RUNTIME_POLICY.yaml`.
- **Sandbox (SEC-05):** allowlist `external_roots` na policy; `**` puro proibido em `allowed_write`.
- **Limites (SEC-06):** `resource_limits` na policy (contagem/bytes de file_updates, bytes de resposta de adapter), reject `RESOURCE_LIMIT_EXCEEDED`, staging descartado sem efeitos parciais.

### Fase 3 — Dívida arquitetural (G06 → G07) · P1/P2 · esforço alto

- **Decomposição (ARC-01):** `service.py` → `service_core` / `submission` / `execution` / `task_admin` / `seeds`, com `service.py` mantido como fachada de re-export (zero breaking change). Gate: nenhum módulo >500 linhas (teste de inventário).
- **Path-safety único (ARC-05):** `utils.safe_rel_path` substitui as três implementações; casos de borda (`..`, `/`, `C:`, `runtime://`) num único teste parametrizado.
- **Snapshot no caminho quente (ARC-02):** submit/run carregam snapshot+tail; invariante: hash idêntico ao replay completo; orçamento de ≤2 `materialize()` por submit (instrumentado).
- **Dieta de eventos (ARC-04):** `verify_emission=external` na policy — `verify.start/ok` deixam de ser persistidos por submit; verificação vira comando externo (`verify --record`). Modo inline permanece default até um major.

---

## 4. Critérios de aceite globais (gates de QA)

1. **Determinismo preservado:** replay de store de referência projeta hash idêntico antes e depois de cada fase (golden test obrigatório em G02, G06 e G07).
2. **Fail-closed:** toda nova validação rejeita por código estruturado registrado em `reject_codes.py` (o inventory test detecta órfãos).
3. **Sem efeitos parciais:** qualquer rejeição descarta staging integralmente (já coberto por `test_atomic_file_effects`, estendido em G05).
4. **Compatibilidade:** suite existente (218 testes) passa sem alteração de asserts em todas as fases; mudanças de default (identity.strict, verify_emission) entram com modo legado disponível.
5. **CI como autoridade:** nenhuma task `qa` aprova com CI vermelho.

---

## 5. Como executar pelo próprio ESAA

```powershell
# 1. validar o template
python -m esaa --root . verify

# 2. ativar o roadmap de correção (workspace dedicado recomendado,
#    pois este repositório é o próprio framework em desenvolvimento)
#    — usar o fluxo roadmap.activate / plugin com o template:
#    .roadmap/roadmap.correction-plan.template.json

# 3. acompanhar
python -m esaa --root . eligible
python -m esaa --root . roadmap status --detail
```

Observação: executar o plano **no próprio repositório do framework** significa que as tasks `impl` modificam o código que as governa. Recomenda-se branch dedicada por grupo e, para G02/G04 (que alteram `store.py`), validar com a versão publicada do `esaa-core` como harness, não com a árvore em edição.

---

## 5.1. Adendo — G08: Proveniência de runner (2026-06-09)

Achado pós-execução de G01: o event store registra o **papel** (`actor`:
agent-spec/impl/qa) mas não o **principal** que o exerceu (runner: Claude
Cowork, Claude Code, Codex, humano). Tríade admitida no roadmap governado como
**T-004/T-005/T-006** (targets PROV-01, PROV-02): bloco `runner` por evento
resolvido pelo single writer (opção A) + registro/validação de runners no
`agents_swarm.yaml` (opção C). **Recomendação de ordem:** executar G08 antes
de G02 (hash chain), para que a cadeia de hash já nasça cobrindo proveniência.
Nota: a numeração T-004+ do template original (G02) será reatribuída quando
os grupos G02..G07 forem admitidos no roadmap governado.

## 6. Resumo executivo

| Fase | Grupos | Prioridade | Entrega central |
|------|--------|-----------|-----------------|
| 0 | G01 | P0 | CI verde, lint, versão única, repo limpo |
| 1 | G02, G03 | P0 | Store tamper-evident + identidade autenticada |
| 2 | G04, G05 | P1 | Locks resilientes, retry, sandbox e limites |
| 3 | G06, G07 | P1/P2 | service decomposto, path-safety único, submit sublinear |

O plano fecha as duas vulnerabilidades críticas (SEC-01, SEC-02) antes de qualquer refatoração, usa a fundação de CI para impedir regressão, e termina atacando a dívida estrutural sem quebrar a API pública nem o determinismo do replay.
