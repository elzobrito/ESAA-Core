# Grok e Antigravity: execução governada com ESAA

🌐 **Português** · [English](esaa-grok-antigravity.en.md)

## 1. Versão e autoridade

Este guia descreve a extensão opcional de verificação do protocolo **0.4.2**. A base de armazenamento e as projeções mantêm o schema 0.4.1. Após registrar eventos verification.configure/run, runtimes antigos podem rejeitar ações desconhecidas; não faça downgrade para um leitor que não reconheça essa extensão. Use o checkout/candidato que contém essas interfaces; uma instalação global anterior não é atualizada por modificar o código-fonte.

O operador cria tarefas e concede permissões; o Orchestrator é o único escritor dos eventos e efeitos finais. Actor identifica o agente que assume um papel autorizado na tarefa, runner é quem executa a submissão e modelo é a LLM utilizada. Identifique o runner real com `--runner` ou `ESAA_RUNNER_ID`; no modo strict ele precisa estar registrado. Não atribua ao Antigravity uma submissão executada pelo Grok. A revisão segue a política e as autorizações do workspace.

## 2. Divisão de trabalho

O Grok seleciona a tarefa com `eligible`, obtém `dispatch-context` e entrega esse contexto e os conteúdos referenciados necessários ao Antigravity. O auxiliar propõe `claim`; depois da aceitação e da atualização do contexto, prepara o candidato e as verificações. Cada envelope tem uma ação e `prior_status` coerente. `claim` e `complete` são submissões separadas. A resposta submetida é JSON puro; a conversa não precisa ser JSON.

O responsável pelo claim entrega o complete. `file_updates` aparece somente no complete. Prepare os candidatos em área permitida e deixe os efeitos finais para o Orchestrator. `base_sha256` detecta base divergente na aplicação de edits; não impede uma ferramenta de escrever diretamente fora do protocolo.

## 3. Interfaces

```text
verification enable --config CONFIG.json [--dry-run]
verification show
verification run TASK-ID --candidate COMPLETE.json --actor ACTOR [--dry-run]
verification result RUN-ID

task create TASK-ID ... [--executable-check ID]...
task amend TASK-ID [--executable-check ID]...
hotfix create --issue-id ISS --fixes TASK-ID [--scope-patch PATH]...
  [--boundary-grant PATTERN]... [--output PATH]... [--executable-check ID]...
task amend TASK-ID [--boundary-grant PATTERN]... | [--clear-boundary-grants]
task amend HOTFIX-ID [--scope-patch PATH]...
complete TASK-ID --actor ACTOR --check TEXT [--execution-id RUN-ID] ...

task list [--status STATUS]... [--kind KIND] [--assigned-to ACTOR]
  [--source event_store|planned|all] [--limit N] [--cursor TOKEN] [--format json|table]
activity list [--task-id ID] [--action ACTION]... [--exclude-action ACTION]...
  [--hide-verify] [--after-seq N] [--limit N] [--format json|jsonl|table]
```

Grants são explícitos e nunca herdados. Substituir grants ou escopo só é permitido em `todo`; `--clear-boundary-grants` é incompatível com `--boundary-grant`. Grants não sobrepõem proibições explícitas ou safe-path. Scope runtime legado continua sujeito aos controles de efeitos externos; a verificação executável desta versão aceita apenas arquivos locais regulares, sem symlinks.

## 4. Catálogo e execução

`verification enable` recebe um catálogo autorizado pelo operador e registra `verification.configure`; não é um campo livre no envelope do agente. A ativação acrescenta propriedades opcionais aos schemas, preserva extensões compatíveis e recusa conflitos. O dry-run mostra o plano sem persistir. Não use bootstrap com force para migrar um projeto existente.

Cada check declara `id`, `image` fixada por digest, `command` como array de argumentos e `inputs` como padrões fnmatch. `cwd` é relativo, com default `.`. Campos desconhecidos, caminhos protegidos/externos e IDs desconhecidos são rejeitados. Os checks de uma tarefa são os IDs passados por `--executable-check`.

Defaults: timeout 60 s, 1 CPU, 512 MiB de memória, 128 processos, 64 MiB para o workspace candidato e 1 MiB por fluxo de log. Limites configuráveis: timeout 1–3600 s; CPU 1–8; memória 32–8192 MiB; processos 16–1024; workspace 1–1024 MiB; logs 1 KiB–8 MiB. A imagem precisa estar localmente disponível e conter `/bin/sh`, `tar` e os executáveis dos checks. Preparar a imagem é uma operação separada do operador; o executor não baixa imagens nem instala dependências.

O executor envia somente as entradas autorizadas e o conteúdo candidato para tmpfs privado. Não há mounts do host, rede, credenciais herdadas do host ou socket Docker dentro do contêiner. A raiz é somente leitura; o processo é usuário 65534, sem capabilities e com no-new-privileges. Não há fallback para processo local. O operador deve escolher imagens confiáveis e padrões de entrada que não incluam segredos.

Um resultado registra checks, imagens, exit codes, duração, timeout/cancelamento, hashes e logs limitados. `verification result` verifica o digest do resultado e a integridade dos logs. O runner e a proveniência ficam no evento do Orchestrator.

## 5. Vínculo com a entrega e falhas

Copie o run_id aprovado para `activity_event.verification.execution_id`; o atalho `complete` também aceita `--execution-id`. O gate compara tarefa, actor, ciclo, configuração vigente, entradas e conteúdo normalizado do candidato. Mudança nas entradas durante execução produz resultado stale. Qualquer nova ativação do catálogo invalida evidências anteriores, mesmo com configuração equivalente. `request_changes` inicia outro ciclo e exige nova execução.

O complete revalida antes da submissão e sob lock, inclusive no caminho de adapters. Entregas do mesmo batch que alterem entradas de outra verificação são recusadas. O complete não executa testes. Dry-run, verify e replay também não executam checks. Docker ausente, imagem não local, timeout, cancelamento, log alterado ou evidência faltante não autorizam aplicar o candidato.

Os checks declarativos continuam aceitos nas tarefas sem `executable_checks`; os mínimos de 1 check comum e 2 no hotfix permanecem. Evidência executável não substitui avaliação de requisitos, inspeção visual ou QA. Em falha depois do append e antes de completar efeitos, interrompa a operação e use o fluxo de diagnóstico/recuperação de efeitos; não edite eventos ou projeções.

## 6. Demonstração sintética reproduzível

A demonstração abaixo usa um arquivo sintético chamado tetris.py em um workspace novo. Seu único requisito é conter o marcador fixed. Ela comprova o fluxo, sem testar Pygame, jogabilidade, acessibilidade ou o Tetris original. A imagem Alpine fixada precisa já existir localmente. Para o jogo real, configure imagem e comandos com testes reais de lógica, renderização e interação conforme a tarefa.

```bash
set -e
esaa_demo_root="$(mktemp -d -t esaa-grok-demo-XXXXXX)"
esaa_demo_candidate="$(mktemp -t esaa-candidate-XXXXXX.json)"
esaa_demo_result="$(mktemp -t esaa-result-XXXXXX.json)"
esaa_demo_config="$(mktemp -t esaa-checks-XXXXXX.json)"
export ESAA_RUNNER_ID=grok-bot
python -m esaa --root "$esaa_demo_root" bootstrap --profile public
python -m esaa --root "$esaa_demo_root" init
python -m esaa --root "$esaa_demo_root" chain init
cat > "$esaa_demo_config" <<'JSON'
{"checks":[{"id":"marker","image":"alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce","command":["/bin/sh","-c","grep -q fixed tetris.py"],"inputs":["tetris.py"]}]}
JSON
python -m esaa --root "$esaa_demo_root" verification enable --config "$esaa_demo_config" --dry-run
python -m esaa --root "$esaa_demo_root" verification enable --config "$esaa_demo_config"
python -m esaa --root "$esaa_demo_root" task create T-DEMO --kind impl \
  --title "Synthetic candidate marker" --output tetris.py \
  --boundary-grant tetris.py --executable-check marker
python -m esaa --root "$esaa_demo_root" dispatch-context T-DEMO
python -m esaa --root "$esaa_demo_root" claim T-DEMO --actor agent-impl
python -m esaa --root "$esaa_demo_root" dispatch-context T-DEMO
cat > "$esaa_demo_candidate" <<'JSON'
{"activity_event":{"action":"complete","task_id":"T-DEMO","prior_status":"in_progress","verification":{"checks":["Synthetic marker checked in Docker"]}},"file_updates":[{"path":"tetris.py","content":"# fixed\n"}]}
JSON
python -m esaa --root "$esaa_demo_root" verification run T-DEMO \
  --candidate "$esaa_demo_candidate" --actor agent-impl > "$esaa_demo_result"
python - "$esaa_demo_candidate" "$esaa_demo_result" <<'PY'
import json,sys
from pathlib import Path
candidate=Path(sys.argv[1]); payload=json.loads(candidate.read_text())
result=json.loads(Path(sys.argv[2]).read_text())
assert result['status']=='passed'
payload['activity_event']['verification']['execution_id']=result['run_id']
candidate.write_text(json.dumps(payload))
PY
python -m esaa --root "$esaa_demo_root" submit --actor agent-impl --dry-run "$esaa_demo_candidate"
python -m esaa --root "$esaa_demo_root" submit --actor agent-impl "$esaa_demo_candidate"
python -m esaa --root "$esaa_demo_root" review T-DEMO --actor agent-qa --decision approve
python -m esaa --root "$esaa_demo_root" task list --status done --format table
python -m esaa --root "$esaa_demo_root" activity list --hide-verify --format table
python -m esaa --root "$esaa_demo_root" verify
python -m esaa --root "$esaa_demo_root" verify --chain
```

## 7. Hotfix, consultas e métricas

Em defeito posterior ao done, reporte uma issue sem `--fixes` e então crie o hotfix com escopo, outputs, grants e checks necessários. Alternativamente, `issue report --fixes` cria automaticamente um hotfix com defaults: não execute outra criação para a mesma issue. Um hotfix em todo pode ser ajustado; a tarefa original permanece done. A aprovação de hotfix vinculado pode resolver a issue automaticamente.

`task list` reúne tarefas do store e planejadas por plugins; uma tarefa planejada ainda não é prova de execução. Status repetidos usam OR; dimensões diferentes são combinadas. A ordenação é por task_id; cursor vincula filtros, fontes e sequência observada. Se o estado mudar, QUERY_CURSOR_STALE pede reiniciar a consulta. Limites padrão/máximo: 100/1000.

`activity list` ordena por event_seq. Inclusões e exclusões filtram ações; exclusão prevalece. `--task-id` compara o task_id do payload, sem associação transitiva a issues ou tarefas originais. `--hide-verify` oculta verify.* somente na saída. Retome por next_after_seq; a sequência observada e has_more acompanham o JSON. Workspace não inicializado retorna erro sem criar diretórios. Formatos table e jsonl são apresentação, não alteração do store.

`attempts_total` conta output.rejected. `--runner` registra proveniência; tokens e latência exigem telemetria real por runner metrics. Valores desconhecidos não devem ser inventados. Verify confirma consistência das projeções; a cadeia ancorada acrescenta verificação de hashes, sem provar correção funcional nem autenticar retroativamente um passado não ancorado.

## Referências

- [Primeiros passos](esaa-getting-started.md)
- [Referência CLI](esaa-cli-reference.md)
- [Cenários](esaa-cenarios.md)
