# G02 — Especificação: Integridade do Event Store (hash chain)

> Tarefa: T-008 (spec) · Targets: SEC-01, SEC-03 · Depende: T-002, T-005 (G08)
> Motivação direta: `activity.jsonl` é JSONL puro — quem tem escrita no arquivo
> reescreve a história sem detecção. Incidente real neste workspace (evento 85
> truncado por escrita concorrente) provou que nem corrupção acidental é
> detectada antes do parse falhar.

## SEC-01 — Cadeia de hash append-only

### Princípio inegociável

O store é imutável: a migração NÃO reescreve linhas existentes. A cadeia é
introduzida por um **evento âncora**, preservando o invariante append-only.

### Desenho

1. **`chain.anchor`** (novo action, exclusivo do Orchestrator): evento que
   registra `anchored_through_seq` (N) e `anchor_sha256` = SHA-256 da
   concatenação canônica das linhas 1..N do store (bytes exatos, LF).
   Tudo até N passa a ser coberto retroativamente pela âncora.
2. **Eventos pós-âncora** ganham dois campos de topo:
   - `prev_event_hash`: `event_hash` do evento anterior (para o primeiro
     pós-âncora: `anchor_sha256`).
   - `event_hash`: SHA-256 do JSON canônico do evento (sort_keys,
     separators compactos, ensure_ascii=False) **sem** o próprio `event_hash`.
   O bloco `runner` (G08) fica DENTRO do hash — proveniência coberta.
3. **Validação no parse** (`parse_event_store`): se o store contém
   `chain.anchor`, todo evento posterior deve encadear corretamente;
   quebra → `CorruptedStoreError("CHAIN_BROKEN", ...)` fail-closed.
   Stores sem âncora (legados) parseiam como hoje (modo pré-G02).
4. **`verify --chain`**: comando independente que revalida âncora + cadeia
   inteira sem depender do estado em memória do writer; saída inclui
   `chain_status: ok|broken|unanchored` e o seq da primeira quebra.
5. **`chain init`**: emite o `chain.anchor` (idempotente: segunda chamada
   sem eventos novos é no-op; re-ancoragem só com `--force`, auditada).

### O que a cadeia NÃO cobre (explícito no threat model)

Truncamento total do arquivo + remoção da âncora (atacante com escrita
irrestrita reconstrói store inteiro sem âncora). Mitigação: hash da âncora
publicado fora do store (`.roadmap/chain.head`, commit git, ou snapshot
manifest). Registrado como follow-up de hardening.

## SEC-03 — `reviewer_role` carimbado, não declarado

Hoje `_reviewer_role` entra no `payload` (derivado do ator no submit) e o
projector confia nele no replay. Mudança:

1. Campo promovido a **nível de evento** (`reviewer_role`), escrito pelo
   Orchestrator junto com `actor`/`runner` — nunca aceito do envelope
   (já bloqueado por additionalProperties; adicionar a forbidden_fields).
2. No **submit**, o role é resolvido do swarm como hoje (FIX-1807).
3. No **replay**, o projector usa o campo carimbado do evento (determinismo:
   replay não depende do estado atual do swarm). A integridade do carimbo é
   garantida pela cadeia SEC-01 — sem cadeia íntegra, replay é rejeitado.
4. Compatibilidade: eventos legados com `_reviewer_role` no payload continuam
   aceitos pelo projector (caminho de leitura dual até major release).

## Critérios de aceite

1. Edição, remoção, inserção ou reordenação de qualquer linha pós-âncora →
   `CHAIN_BROKEN` no parse e no `verify --chain`.
2. Adulteração de linha pré-âncora → detectada por `verify --chain` via
   `anchor_sha256`.
3. `chain init` em store legado preserva replay byte-idêntico das projeções.
4. Evento `review` com cadeia íntegra prova `reviewer_role` não forjado;
   alteração manual do campo quebra a cadeia.
5. Suíte completa verde; golden replay pré/pós-âncora com hash idêntico.

## Novos códigos

`CHAIN_BROKEN`, `CHAIN_ALREADY_ANCHORED`, `CHAIN_NOT_ANCHORED` — registrados
em `reject_codes.py` (M-04).
