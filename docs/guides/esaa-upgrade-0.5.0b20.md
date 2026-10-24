# Atualização para esaa-core 0.5.0b20

🌐 **Português** · [English](esaa-upgrade-0.5.0b20.en.md)

## 1. O que muda

A 0.5.0b20 anuncia o protocolo **0.4.2**, que acrescenta uma extensão **opcional** de verificação executável. O armazenamento e as projeções continuam no schema **0.4.1**; um projeto que não ativar a extensão segue funcionando como na 0.5.0b19. Confira com:

```bash
esaa --version
# esaa 0.5.0b20 (protocol 0.4.2, storage protocol 0.4.1, esaa 0.4.x)
```

Novidades relevantes para Grok, Antigravity e outros runners:

- `verification enable/show/run/result`: catálogo de checks autorizado pelo operador e executado em Docker isolado, com imagem fixada por digest, sem rede, sem mounts do host e sem fallback local.
- `--executable-check ID` em `task create`, `task amend` e `hotfix create`; o complete dessas tarefas exige `verification.execution_id` (ou `complete --execution-id RUN-ID`) de um resultado aprovado e vinculado a tarefa, actor, ciclo, configuração, entradas e candidato.
- `hotfix create` com `--boundary-grant`, `--output` e `--executable-check`; `task amend` com grants (`--boundary-grant`, `--clear-boundary-grants`) e `--scope-patch`, permitidos somente em `todo`.
- Consultas: `task list` (filtros, paginação por cursor, `--format table`) e `activity list` (filtros por ação, `--hide-verify`, `--after-seq`, formatos `json|jsonl|table`).
- Registro de actors e identidade com histórico assinado (`esaa actor ...`), opcional e preservado no replay legado.
- Âncora da cadeia de hashes gerada sob lock e projetada na mesma transação.
- APIs Python `create_task`, `create_hotfix` e `amend_task` preservam argumentos posicionais; os novos parâmetros são somente nomeados.

## 2. Antes de atualizar: backup

O event store é a fonte de verdade. Faça uma cópia do diretório `.roadmap/` (ou commit) antes de atualizar e confirme o estado atual:

```bash
esaa verify
esaa verify --chain        # se a cadeia estiver ancorada
cp -a .roadmap ".roadmap.bak-$(date +%Y%m%d%H%M%S)"
```

## 3. Atualizar

```bash
python -m pip install --user --upgrade --pre esaa-core==0.5.0b20
esaa --version
esaa verify
```

Use o mesmo Python/CLI que o runner já utiliza; atualizar o código-fonte de um checkout não atualiza uma instalação global, e vice-versa. Para ambientes isolados, instale em um venv e chame `python -m esaa`.

Não rode `bootstrap --force` para migrar um projeto existente: ele não é necessário e pode sobrescrever contratos personalizados. Os templates novos só são relevantes para projetos criados do zero.

## 4. Ativar a verificação executável (opcional)

1. Prepare localmente uma imagem confiável, fixada por digest, contendo `/bin/sh`, `tar` e os executáveis dos checks (o executor nunca baixa imagens).
2. Escreva o catálogo e ative-o, primeiro em dry-run:

```bash
esaa verification enable --config checks.json --dry-run
esaa verification enable --config checks.json
esaa verification show
```

3. Marque as tarefas: `esaa task amend T-ID --executable-check unit` (tarefa em `todo`).
4. Fluxo do runner: `claim` → preparar o candidato complete → `esaa verification run T-ID --candidate complete.json --actor agent-impl` → copiar o `run_id` aprovado para `activity_event.verification.execution_id` → `submit` (dry-run e real) → `review`.

O passo a passo completo e uma demonstração sintética reproduzível estão em [Grok e Antigravity](esaa-grok-antigravity.md).

## 5. Limites de migração e compatibilidade

- **Sem downgrade após ativar.** Depois de registrar `verification.configure`/`verification.run`, runtimes anteriores à 0.5.0b20 podem rejeitar essas ações no replay. Mantenha todos os leitores do projeto na b20 ou superior.
- Uma nova ativação do catálogo invalida evidências anteriores; `request_changes` inicia novo ciclo e exige nova execução.
- Tarefas sem `executable_checks` continuam aceitando checks declarativos (mínimo 1; hotfix, 2).
- Grants são explícitos, nunca herdados, e não sobrepõem proibições nem safe-path. Alterar grants/escopo só em `todo`; status nunca volta.
- `complete`, `verify`, dry-run e replay não executam checks. Docker ausente, imagem não local, timeout ou evidência faltante bloqueiam o complete de tarefas configuradas.
- Evidência executável não substitui avaliação de requisitos, inspeção visual ou QA.
- Nunca edite eventos ou projeções à mão; em falha, use issue e hotfix.

## 6. Para o Grok

- Identifique-se como runner: `--runner grok-bot` ou `ESAA_RUNNER_ID=grok-bot`.
- Uma tarefa por vez: `eligible` → `dispatch-context` → `claim` → `complete` → `review`; `claim` e `complete` são submissões separadas.
- Consulte o estado só pela CLI: `task list`, `state`, `activity list --hide-verify`, `verify`.
- Ao delegar a um auxiliar (por exemplo Antigravity), entregue o `dispatch-context` e revise tudo o que voltar; a submissão é registrada com o runner real.
