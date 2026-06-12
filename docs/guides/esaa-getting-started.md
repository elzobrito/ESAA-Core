# ESAA — Primeiros passos

Guia prático: do zero até o primeiro ciclo completo `todo → in_progress →
review → done` num workspace governado pelo ESAA.

## 1. Instalação

```powershell
pip install esaa-core
esaa --version   # ex.: esaa 0.5.0b9 (protocol 0.4.1, esaa 0.4.x)
```

O pacote instala o comando `esaa` (equivalente a `python -m esaa`). Não há
servidor, daemon nem MCP: tudo é CLI local + arquivos no diretório do projeto.

## 2. Criar o workspace

Na raiz do projeto:

```powershell
$env:ESAA_RUNNER_ID = "codex"      # ou use --runner codex em cada comando
esaa bootstrap --profile public     # contratos, schemas e guias mínimos
esaa init                           # estado canônico limpo (event store + projeções)
```

- `bootstrap --profile public` instala os templates de governança empacotados
  (`AGENT_CONTRACT.yaml`, `ORCHESTRATOR_CONTRACT.yaml`, schemas, policies).
  `--profile production` instala a variante endurecida. Use `--force` para
  sobrescrever um bootstrap anterior.
- `esaa init` emite os eventos de inicialização e cria `.roadmap/activity.jsonl`
  (fonte da verdade) e as projeções `roadmap.json`, `issues.json`,
  `lessons.json` — incluindo o reseed das lessons baseline LES-0001/2/3.

Tudo que o ESAA governa vive em `.roadmap/`. **Nunca edite esses arquivos à
mão** — toda mutação passa pelo Orchestrator.

### Flags globais

Todo comando aceita:

- `--root <path>` — raiz do workspace (default: diretório atual). O estado é
  **por workspace**: cada pasta com `.roadmap/` é um universo independente.
- `--runner <id>` — identidade do runner carimbada em cada evento (G08), ex.:
  `--runner codex`, `--runner claude-code`. Pode vir de `ESAA_RUNNER_ID`.
  Em workspaces com policy strict, comandos que escrevem eventos falham sem um
  runner registrado.

## 3. Criar tarefas

```powershell
esaa task create T-LOGIN-SPEC --kind spec `
  --title "Especificar fluxo de login" `
  --description "Documentar o fluxo de autenticacao SSO" `
  --output docs/spec/login.md --target documentation

esaa task create T-LOGIN-IMPL --kind impl `
  --title "Implementar fluxo de login" `
  --depends-on T-LOGIN-SPEC `
  --output src/auth/login.php

esaa task create T-LOGIN-QA --kind qa `
  --title "Validar fluxo de login" `
  --depends-on T-LOGIN-IMPL `
  --output docs/qa/login.md
```

- `--kind` define as **boundaries** de escrita: `spec` → `docs/**`;
  `impl` → `src/**`, `tests/**`; `qa` → `docs/qa/**`, `tests/**` (proibido `src/**`).
- `--boundary-grant <fnmatch>` concede um padrão extra de escrita só para
  aquela tarefa (autoridade do operador, T-2070).
- `--dry-run` simula o evento e mostra o hash resultante sem persistir —
  disponível em praticamente todas as transições.

## 4. Descobrir o que é executável

```powershell
esaa eligible
```

Retorna as tarefas executáveis agora (dependências satisfeitas) e os
`parallel_groups` — grupos que podem rodar em paralelo sem conflito.

Para uma tarefa específica:

```powershell
esaa state T-LOGIN-SPEC              # status + próxima action esperada
esaa dispatch-context T-LOGIN-SPEC   # contexto mínimo para despachar a um agente
```

## 5. O ciclo governado (two-step)

O protocolo exige **uma action por invocação** (LES-0001). O ciclo mínimo:

```powershell
# Invocação 1 — reivindicar (todo → in_progress)
esaa claim T-LOGIN-SPEC --actor agent-spec

# Invocação 2 — concluir com evidência e arquivos (in_progress → review)
esaa complete T-LOGIN-SPEC --actor agent-spec `
  --check "docs/spec/login.md cobre os 3 fluxos exigidos" `
  --file-updates updates.json `
  --notes "Especificacao do fluxo de login"

# Invocação 3 — revisão por QA independente (review → done | in_progress)
esaa review T-LOGIN-SPEC --actor agent-qa --decision approve
```

Pontos críticos:

- `--file-updates` recebe um **arquivo JSON** (ou `-` para stdin) com um array
  `[{"path": "...", "content": "..."}]` — ou a forma compacta `edits` com
  `base_sha256`, que rejeita patch sobre arquivo desatualizado. Os arquivos são
  aplicados **pelo Orchestrator**, com staging atômico em `.roadmap/staging/`.
- `--check` é repetível e obrigatório: mínimo 1 para `spec`/`impl`/`qa`,
  2 para hotfix.
- `review` exige ator com **role QA** (`review_authorization=qa_role`);
  quem completa não se auto-aprova. `--decision request_changes` devolve a
  tarefa para `in_progress`.
- Quem completa deve ser quem reivindicou (`assigned_to == actor`), senão
  `LOCK_VIOLATION`.

### Execução automática

```powershell
esaa run --steps 3                 # executa N passos com o adapter mock
esaa run --adapter http --llm-url https://... --until-done
```

`run` despacha as tarefas elegíveis a um adapter (mock para testes, HTTP para
um endpoint LLM), com `--parallel N` por onda. Para runners interativos
(Codex/Claude Code), veja o [guia de runners](esaa-runners-codex-claude-code.md).

## 6. Verificar a integridade

```powershell
esaa verify           # reprojeta e compara hash → ok | mismatch | corrupted
esaa verify --chain   # também valida a hash chain do event store
esaa project          # força reprojeção dos read models
esaa replay --until 42 --no-write   # estado em qualquer ponto do histórico
```

`verify` é a defesa contra drift: qualquer edição manual nas projeções ou no
event store é detectada por hash.

## 7. Quando algo dá errado

```powershell
# Bloqueio durante execução → issue com evidência
esaa issue report T-LOGIN-SPEC --actor agent-spec `
  --issue-id ISS-LOGIN-SPEC --severity medium `
  --title "Dependencia ausente" `
  --symptom "Nao ha contrato de callback no workspace" `
  --repro-step "Executar esaa dispatch-context T-LOGIN-SPEC"

# Defeito em tarefa done (imutável) → hotfix, nunca reabertura
esaa issue report T-LOGIN-SPEC --actor agent-qa `
  --issue-id ISS-LOGIN-DONE --severity high `
  --title "Spec aprovada deixou lacuna" `
  --symptom "Fluxo de erro nao foi documentado" `
  --repro-step "Comparar spec com teste de QA" `
  --fixes T-LOGIN-SPEC
esaa hotfix create --issue-id ISS-LOGIN-DONE --fixes T-LOGIN-SPEC `
  --scope-patch src/hotfix/

# Output inválido de agente → rejeição explícita registrada
esaa reject T-X --error-code ACTION_COLLAPSE --source-action complete --message "..."
```

Veja a demonstração ponta a ponta: `esaa scenario hotfix`.

## 8. Manutenção

```powershell
esaa snapshot --before 100 --compact   # checkpoint + compactação auditável
esaa activity clear --dry-run          # conferir plano de limpeza
esaa activity clear --force            # backup e reinício do event store
esaa metrics                           # métricas estruturadas do runtime
```

## Leia em seguida

- [Referência completa do CLI](esaa-cli-reference.md)
- [Operando Codex e Claude Code como runners](esaa-runners-codex-claude-code.md)
- [Por que usar o ESAA](esaa-why.md)
