# G06 — Bootstrap `--preserve-guides` e `--merge-guides`

## Problema

Hoje o `bootstrap` trata guias (`AGENTS.md`, `.claude/CLAUDE.md`, `README.md`) como
templates substituíveis:

- **sem `--force`**: qualquer arquivo alvo existente aborta tudo (`BOOTSTRAP_TARGET_EXISTS`);
- **com `--force`**: sobrescreve guias customizados com stubs mínimos (3 linhas).

Projetos que já têm orientação para agentes precisam instalar governança ESAA **sem
perder** contexto local — ou **incorporá-lo** de forma determinística.

Implementação atual: `src/esaa/bootstrap.py`, testes em `tests/test_public_beta_release.py`.

## Objetivos

| Objetivo | Flag |
|----------|------|
| Instalar `.roadmap/` e pular guias existentes | `--preserve-guides` |
| Instalar governança e compor guias (contrato ESAA + conteúdo do projeto) | `--merge-guides` |
| Manter compatibilidade com comportamento atual | default inalterado |

**Fora de escopo (v1):**

- merge automático de YAML em `.roadmap/` (contratos normativos);
- unificação automática de `CLAUDE.md` na raiz com `.claude/CLAUDE.md`;
- diferenciação real de `--profile production` (ainda não implementada).

## Escopo dos “guides”

Arquivos cobertos (derivados de `AGENT_GUIDE_TEMPLATE_FILES`):

| Template interno | Destino no workspace |
|------------------|----------------------|
| `AGENTS.md` | `AGENTS.md` |
| `CLAUDE.md` | `.claude/CLAUDE.md` |
| `README.md` | `README.md` |

Governança (15 arquivos em `.roadmap/`) **não** entra em preserve/merge — continua com
regras atuais de existência/`--force`.

## Semântica das flags

### Matriz de composição

| `--force` | `--preserve-guides` | `--merge-guides` | Governança existente | Guias existentes |
|-----------|----------------------|------------------|----------------------|------------------|
| ✗ | ✗ | ✗ | existe | `BOOTSTRAP_TARGET_EXISTS` (atual) |
| ✗ | ✓ | ✗ | existe | bootstrap **falha** só por governança |
| ✗ | ✗ | ✓ | existe | bootstrap **falha** só por governança |
| ✗ | ✓/✓ | ✗/✓ | ausente | guias: preservar ou mesclar |
| ✓ | ✗ | ✗ | sobrescreve | sobrescreve (atual) |
| ✓ | ✓ | ✗ | sobrescreve | **preserva** guias |
| ✓ | ✗ | ✓ | sobrescreve | **mescla** (atualiza região ESAA) |
| ✓ | ✓ | ✓ | — | `BOOTSTRAP_FLAGS_CONFLICT` |

**Regras:**

- `--preserve-guides` e `--merge-guides` são **mutuamente exclusivos**.
- `--force` afeta **somente governança** quando uma flag de guias está ativa.
- Default (sem flags de guias): `--force` continua sobrescrevendo os 18 arquivos.

### `--preserve-guides`

**Comportamento:**

1. Remove guias da checagem `existing` que dispara `BOOTSTRAP_TARGET_EXISTS`.
2. Na escrita: se o guia existe → **não toca**; se ausente → copia template do pacote.
3. Governança: inalterada (bloqueia se existir sem `--force`; sobrescreve com `--force`).

**Caso de uso:**

```bash
esaa bootstrap --preserve-guides          # primeira vez: gov + guias ausentes
esaa bootstrap --preserve-guides --force  # refresh contratos; guias intactos
```

### `--merge-guides`

**Comportamento:** guias viram documento de duas regiões com marcadores HTML (estáveis,
testáveis, compatíveis com Markdown).

```markdown
<!-- esaa:bootstrap:contract:begin -->
# AGENTS.md — Contrato operacional ESAA
... template do pacote (versão completa, não stub) ...
<!-- esaa:bootstrap:contract:end -->

<!-- esaa:bootstrap:project:begin -->
## Contexto do projeto
... conteúdo preservado do workspace ...
<!-- esaa:bootstrap:project:end -->
```

**Primeira execução (guia existente, sem marcadores):**

1. Lê conteúdo original integralmente.
2. Escreve: região `contract` = template empacotado; região `project` = conteúdo original.
3. Se guia ausente: escreve contrato + seção `project` vazia com placeholder:

```markdown
<!-- esaa:bootstrap:project:begin -->
## Contexto do projeto

_Adicione aqui regras específicas do seu projeto._
<!-- esaa:bootstrap:project:end -->
```

**Reexecução com `--force --merge-guides`:**

- Governança: sobrescreve.
- Guias: substitui **apenas** o bloco `contract`; bloco `project` permanece byte-a-byte.

**Reexecução sem `--force`:**

- Governança existente → falha (como hoje).
- Guias existentes → **não atualiza** região `contract` (idempotente / seguro).

**Estados inválidos → fail-closed:**

| Situação | Código |
|----------|--------|
| Marcadores duplicados ou aninhados incorretamente | `BOOTSTRAP_MERGE_AMBIGUOUS` |
| `begin` sem `end` correspondente | `BOOTSTRAP_MERGE_INVALID` |
| Região `project` ausente em arquivo que já tem marcadores `contract` | `BOOTSTRAP_MERGE_INVALID` |

## Mudanças no pacote de templates

### Templates de guias (`src/esaa/workspace/`)

Hoje `AGENTS.md` e `CLAUDE.md` são stubs de 3 linhas. Para `--merge-guides` fazer sentido:

1. **Promover** o contrato operacional completo (como no repo de referência) para os
   templates empacotados — **ou** um recorte estável versionado (`contract_version: 0.4.1`).
2. Templates usados em `--merge-guides` devem incluir marcadores `contract` internamente
   (gerados na build) **ou** serem envolvidos por `bootstrap.py` na hora da escrita.
3. `--preserve-guides` sem guia existente ainda pode instalar stub mínimo (comportamento
   atual) **ou** template completo — **recomendação:** template completo com marcadores
   vazios em `project`, para consistência.

### `README.md`

Tratamento especial no merge:

- Se `README.md` existir e tiver conteúdo substantivo (> N bytes ou não for template
  ESAA): região `project` = README original; região `contract` = bloco curto “Este
  projeto usa ESAA” + links para `docs/guides/`.
- Evitar duplicar o README inteiro do pacote (~1000 linhas) sobre README de app existente.

## Design de API

### Assinatura Python

```python
def bootstrap_workspace(
    root: Path,
    profile: str = "public",
    force: bool = False,
    *,
    preserve_guides: bool = False,
    merge_guides: bool = False,
) -> dict[str, Any]:
```

### CLI

```text
esaa bootstrap [--profile {public,production}] [--force]
               [--preserve-guides | --merge-guides]
```

Grupo `argparse` mutuamente exclusivo para as duas flags.

### Payload de resposta (extensão)

```json
{
  "status": "bootstrapped",
  "profile": "public",
  "force": true,
  "guide_mode": "preserve|merge|overwrite|default",
  "files_written": ["..."],
  "files_preserved": ["AGENTS.md"],
  "files_merged": [".claude/CLAUDE.md"],
  "protected_paths": ["..."]
}
```

Campos novos opcionais no JSON; testes assertam presença quando aplicável.

### Novos reject codes (`reject_codes.py`)

| Código | Quando |
|--------|--------|
| `BOOTSTRAP_FLAGS_CONFLICT` | `--preserve-guides` + `--merge-guides` |
| `BOOTSTRAP_MERGE_AMBIGUOUS` | múltiplos blocos `contract` ou `project` |
| `BOOTSTRAP_MERGE_INVALID` | marcadores malformados |

Registrar em `ALL_CODES` + `tests/test_reject_codes_inventory.py`.

## Módulos e funções novas

```
src/esaa/bootstrap.py          # orquestração (alterar)
src/esaa/bootstrap_guides.py   # novo: preserve + merge (puras, testáveis)
```

### `bootstrap_guides.py` (funções puras)

```python
GUIDE_MARKER_CONTRACT_BEGIN = "<!-- esaa:bootstrap:contract:begin -->"
GUIDE_MARKER_CONTRACT_END   = "<!-- esaa:bootstrap:contract:end -->"
GUIDE_MARKER_PROJECT_BEGIN  = "<!-- esaa:bootstrap:project:begin -->"
GUIDE_MARKER_PROJECT_END    = "<!-- esaa:bootstrap:project:end -->"

def should_skip_guide(path: Path, preserve_guides: bool) -> bool: ...

def merge_guide_content(
    existing: str | None,
    contract_template: str,
    *,
    readme_mode: bool = False,
) -> str: ...

def extract_regions(text: str) -> tuple[str, str]: ...  # contract, project

def validate_markers(text: str) -> None: ...  # raises ESAAError
```

**Por que módulo separado:** `bootstrap.py` hoje tem ~100 linhas; merge com validação e
README especial merece isolamento e testes unitários sem I/O.

## Fluxo de decisão (implementação)

```text
bootstrap_workspace
  ├─ preserve + merge? → BOOTSTRAP_FLAGS_CONFLICT
  ├─ Montar targets: gov + guides
  ├─ Algum alvo de GOVERNANCE existe sem force? → BOOTSTRAP_TARGET_EXISTS
  └─ Para cada target:
       ├─ governança → write_bytes template
       └─ guia:
            ├─ preserve_guides e existe → skip (files_preserved)
            ├─ merge_guides → merge_guide_content → write_text
            └─ default → overwrite (force ou ausente)
```

**Newline:** usar LF consistente na região `contract` (template); preservar bytes
originais da região `project` na reexecução.

## Casos especiais

### `CLAUDE.md` na raiz

| Situação | v1 |
|----------|-----|
| Só `CLAUDE.md` na raiz | bootstrap cria `.claude/CLAUDE.md`; raiz intacto |
| Só `.claude/CLAUDE.md` | merge/preserve normal |
| Ambos existem, conteúdo diferente | **não fundir automaticamente**; emitir `notes` no JSON: `"root_claude_ignored": true`; documentar no guia |

### Encoding

- Ler/escrita UTF-8; arquivo não-UTF-8 → `BOOTSTRAP_MERGE_INVALID` (fail-closed,
  alinhado a `edits`).

### Compatibilidade com ESAA-Core

Este repositório **não** deve rodar `bootstrap --force` sem `--preserve-guides`. O plano
não altera arquivos do repo de referência — só o runtime.

## Plano de testes

Novo arquivo: `tests/test_bootstrap_guides.py`

### `--preserve-guides`

| Teste | Assert |
|-------|--------|
| `preserve_skips_existing_agents_and_claude` | conteúdo customizado intacto |
| `preserve_writes_missing_guide_only` | gov + guia ausente criado |
| `preserve_still_blocks_existing_governance_without_force` | `BOOTSTRAP_TARGET_EXISTS` |
| `preserve_force_refreshes_governance_keeps_guides` | contrato novo; guias intactos |
| `preserve_does_not_touch_protected_read_models` | regressão do teste existente |

### `--merge-guides`

| Teste | Assert |
|-------|--------|
| `merge_wraps_legacy_agents_without_markers` | original em `project`; contrato presente |
| `merge_force_updates_contract_preserves_project` | só bloco ESAA muda |
| `merge_idempotent_without_force` | segundo run não altera guias |
| `merge_creates_markers_when_guide_missing` | placeholder em `project` |
| `merge_rejects_ambiguous_markers` | `BOOTSTRAP_MERGE_AMBIGUOUS` |
| `merge_rejects_unclosed_marker` | `BOOTSTRAP_MERGE_INVALID` |
| `merge_readme_short_contract_block` | README existente preservado; bloco ESAA curto |

### Flags e CLI

| Teste | Assert |
|-------|--------|
| `bootstrap_flags_conflict` | preserve + merge → erro |
| `bootstrap_cli_preserve_guides` | JSON com `files_preserved` |
| `reject_codes_inventory_includes_new_codes` | inventário completo |

### Regressão

- Manter verde: `tests/test_public_beta_release.py` (ajustar só se semântica default
  mudar — **não deve**).
- `PYTHONPATH=src python -m pytest tests/test_bootstrap_guides.py -q`

## Documentação

| Artefato | Mudança |
|----------|---------|
| `docs/guides/esaa-cli-reference.md` (+ `.en.md`) | sintaxe, matriz de flags, exemplos |
| `docs/guides/esaa-getting-started.md` (+ EN) | cenário “projeto com AGENTS.md existente” |
| `docs/guides/esaa-cenarios.md` (+ EN) | novo cenário: bootstrap em repo legado |
| `readme.md` / `src/esaa/workspace/README.md` | parágrafo em Quickstart |
| `CHANGELOG.md` | entrada `0.5.0b10` (ou próximo beta) |

**Exemplo documentado:**

```bash
# Projeto com Codex/Claude já configurados
esaa bootstrap --preserve-guides

# Incorporar regras locais ao contrato ESAA
esaa bootstrap --merge-guides

# Atualizar contratos sem perder seção do projeto
esaa bootstrap --force --merge-guides
```

## Entrega em PRs (DAG)

```text
PR-1  bootstrap_guides.py + testes unitários (merge/preserve puras)
  ↓
PR-2  bootstrap.py + cli.py + reject_codes + test_bootstrap_guides.py
  ↓
PR-3  Templates workspace (contrato completo + marcadores) + README merge curto
  ↓
PR-4  Documentação (cli-reference, getting-started, cenarios) + CHANGELOG
```

- **PR-1** pode mergear sem mudança de comportamento público.
- **PR-2** é o feature flag visível.
- **PR-3** depende de decisão sobre stub vs contrato completo nos templates.

## Critérios de aceite

1. `esaa bootstrap --preserve-guides` instala governança ausente sem sobrescrever guias
   existentes.
2. `esaa bootstrap --force --preserve-guides` atualiza `.roadmap/*` e preserva guias.
3. `esaa bootstrap --merge-guides` produz arquivo com marcadores e conteúdo original em
   `project`.
4. `esaa bootstrap --force --merge-guides` atualiza só região `contract` em reexecução.
5. `--preserve-guides` e `--merge-guides` juntos → `BOOTSTRAP_FLAGS_CONFLICT`.
6. Comportamento default sem flags **idêntico** ao atual.
7. Projeções protegidas (`activity.jsonl`, `roadmap.json`, etc.) nunca tocadas.
8. Cobertura de testes da matriz acima; suíte completa verde.
9. Documentação PT/EN atualizada.

## Decisões em aberto (fechar antes do PR-3)

| # | Decisão | Recomendação |
|---|---------|--------------|
| D1 | Template de guia sem merge: stub ou contrato completo? | Contrato completo versionado |
| D2 | `README.md` no preserve: pular sempre se existe? | Sim |
| D3 | Sincronizar `AGENTS.md` ↔ `.claude/CLAUDE.md` no merge? | v1: mesma lógica, templates independentes; v2: `--mirror-claude` |
| D4 | Registrar evento no activity.jsonl? | Não — bootstrap é pré-governança, fora do event store |

## Estimativa

| PR | Esforço |
|----|---------|
| PR-1 (lógica pura + testes) | ~1–2 dias |
| PR-2 (integração CLI) | ~1 dia |
| PR-3 (templates) | ~1 dia (depende D1) |
| PR-4 (docs) | ~0.5 dia |