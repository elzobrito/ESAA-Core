# G02 — Write-conflict com escopo do run() (M1)

## Problema

Dentro de um único `run()`, o conjunto de escrita (`wave_write_set`) é reinicializado a cada iteração do `while` (execution.py:215), e `commit_staged` só roda no fim do `run()` (execution.py:359). Consequências:

1. Uma task da iteração N+1 que escreve o mesmo path de uma task da iteração N **não é detectada** como conflito — last-write-wins silencioso no commit.
2. No formato **edits**, o `base_sha256` é validado contra o conteúdo **commitado em disco** (edits.py:74-86), que não inclui o staging pendente da iteração anterior — a garantia anunciada ("sha256 dos bytes atuais") é furada exatamente no cenário em que ela mais importa.
3. O `before_sha256` do segundo `orchestrator.file.write` também fica stale (file_effects.py:139 lê o disco), poluindo a trilha de auditoria.

O cenário é estreito (duas tasks tocando o mesmo path em um único `run()`), mas é corrupção silenciosa de conteúdo — severidade média.

## Decisão (aprovada pelo operador)

**Write-set com escopo do `run()` inteiro.** A segunda escrita no mesmo path dentro de um `run()` vira `output.rejected` com `WRITE_CONFLICT` (fail-closed). Em um `run()` subsequente — pós-commit — o `base_sha256` volta a casar com o disco e a escrita passa. A alternativa (overlay de staging, resolução contra conteúdo staged pendente) foi descartada nesta rodada por custo/superfície de risco; pode ser reavaliada como evolução futura.

A detecção intra-wave existente continua coberta: o set do `run()` contém o da wave.

## Mudanças

1. `src/esaa/execution.py`:
   - criar `run_write_set: list[str] = []` antes do `while` (junto de `new_events`/`staged_file_effects`, ~linha 96);
   - remover a reinicialização per-iteração (`wave_write_set: list[str] = []`, linha 215);
   - passar `wave_write_set=run_write_set` em `_accept_agent_output` (linha 247).
2. `src/esaa/submission.py`: **sem mudanças** — `_accept_agent_output` já detecta conflito contra o set recebido (linhas 383-388) e só o estende com `accepted_write_set` em caso de aceite (reject não envenena o set).
3. `src/esaa/templates/AGENT_CONTRACT.yaml` (bloco `semantics` de edits): registrar que dentro de um mesmo `run()` a segunda escrita no mesmo path é rejeitada com `WRITE_CONFLICT`, e que `base_sha256` valida contra conteúdo commitado em disco.

## Plano de testes

1. `tests/test_write_conflict_policy.py` — novo teste: duas tasks encadeadas por `depends_on` escrevendo o mesmo path (`docs/spec/shared.md`) em **um único** `run(steps=None, parallel=1)`. A primeira completa o ciclo (claim→complete→review→done); a segunda, ao completar com o mesmo path, é rejeitada com `WRITE_CONFLICT`. Asserts: conteúdo da primeira sobrevive ao commit; evento `output.rejected` com `error_code=WRITE_CONFLICT`; `verify()` ok.
2. `tests/test_file_update_edits.py` — variante com **edits**: arquivo base semeado em disco; task 1 escreve conteúdo novo (staged); task 2 envia edits com `base_sha256` do conteúdo base do disco (que casaria, pois o staging não commitou). Antes do fix: passaria e clobberaria. Depois: `WRITE_CONFLICT`. Prova que a garantia do `base_sha256` não é mais furada.
3. Regressão obrigatória: `test_parallel_complete_write_conflict_rejects_without_second_side_effect` (dois `run()` separados, conflito intra-wave) continua verde — escrita sequencial no mesmo path **entre** `run()`s continua permitida.

## Critérios de aceitação

1. Cenário de clobber cross-iteração rejeitado com `WRITE_CONFLICT` nos dois formatos (content e edits).
2. Regressões verdes (intra-wave e cross-run).
3. Semântica documentada no template do contrato.
4. Suíte completa verde.

## Trade-off documentado

Escritas sequenciais legítimas no mesmo path dentro de UM `run()` passam a exigir dois `run()`s. Cenário raro (tríades normalmente têm outputs disjuntos), fail-closed e com caminho de recuperação trivial.
