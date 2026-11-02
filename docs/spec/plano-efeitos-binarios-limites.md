# Plano de alteração: efeitos binários e limites por tarefa no ESAA

Data: 2026-11-02. Situação: planejamento; implementação e migração ainda não realizadas.

## Objetivo

Permitir que o Orchestrator receba, valide, aplique e recupere arquivos binários grandes, com integridade e auditoria equivalentes às dos efeitos de texto. O tamanho máximo por arquivo deve ser definido na criação da tarefa e respeitar uma política superior do workspace. O caso PTB-03 é um teste concreto, não um limite do desenho.

## Diagnóstico confirmado

- O contrato atual de `file_updates` aceita conteúdo textual ou edições textuais; staging, artefatos e recuperação usam UTF-8. Consultar [[agent_result.schema.json|schema ativo]] e [[file_effects.py|efeitos de arquivo]].
- Os limites padrão de [[validator.py|validação]] são 32 atualizações, 2.097.152 bytes por atualização e 8.388.608 bytes no total, salvo configuração válida da política.
- Um FFV1/MKV de três quadros da PTB foi gerado em área temporária e mediu 2.162.463 bytes. Ele excede o limite padrão mesmo antes de considerar transporte. A amostra não estabelece um limite adequado para o showreel inteiro.
- `task.amend` atualmente aceita apenas `todo`. A ML02 está `in_progress`, possui boundary para os destinos e tem a ocorrência ISS-PTB-BINARY-EFFECTS-20261102 aberta.
- O protótipo temporário `/tmp/esaa-binary-dev/src/esaa/binary_payload.py` passou em dois testes unitários simples. Não está integrado, persistido no repositório, auditado nem aprovado para uso.

## Contrato proposto de limites

1. Na criação, aceitar `--max-file-bytes N` e opcionalmente `--max-total-bytes N` e `--max-file-updates N`; valores são inteiros positivos em bytes. O nome das opções e o schema são proposta a validar na implementação.
2. Persistir `resource_limits` no payload do evento `task.create`, na projeção, na saída de `state` e no `dispatch-context`. Rejeitar booleanos, zero, negativos, overflow e valores inválidos; não converter erros silenciosamente em defaults.
3. A política define defaults e tetos máximos administrativos independentes para arquivo, total e quantidade. Uma tarefa sem declaração recebe os limites padrão históricos; uma declaração pode aumentá-los até os tetos explícitos ou reduzi-los. Rejeitar, sem truncar, qualquer pedido acima do teto. Ausência de teto elevado configurado não autoriza aumento.
4. Limites se aplicam a **bytes efetivamente decodificados/aplicados**, depois de resolver edições e antes do commit; a soma inclui todos os efeitos da submissão, textuais e binários. Aplicar limites de transporte e memória separados ao envelope e ao estágio para impedir que dados codificados ou mudanças concorrentes contornem o teto.
5. Os limites ficam congelados por tentativa. Para `todo`, `task.amend` pode alterar mediante evento de operador e mesmas validações. Para tarefas em andamento, implementar evento administrativo específico auditado, com estado anterior/novo, motivo e autorização do operador; só permitir antes de iniciar uma submissão, sob lock e releitura do estado. Nunca mudar `done`. Avaliar compatibilidade com tentativas pendentes e invalidá-las de modo explícito quando necessário.
6. Tamanho não concede acesso. O caminho final continua sujeito a `boundary_grant`, `scope_patch`, denylist, validação do destino e política de efeitos externos; nenhuma concessão pode sobrescrever `forbidden_write`.

Exemplo ilustrativo, a concretizar somente após implementar a CLI e configurar tetos do workspace:

```bash
python -m esaa --root /workspace --runner codex task create VIDEO-001 \
  --kind impl --title 'Renderizar vídeo de referência' \
  --output build/video.mkv --boundary-grant 'build/**' \
  --max-file-bytes 4294967296 --max-total-bytes 8589934592
```

Esses valores são teto da tarefa, não estimativa de uso. Quantidade, disco disponível, retenção e teto do workspace também precisam ser definidos e verificados; uma declaração não reserva espaço automaticamente.

## Contrato proposto para efeito binário

- Adicionar variante explícita e mutuamente exclusiva a `file_updates`: destino, referência a entrada temporária controlada pelo runtime, tamanho esperado e SHA-256. Preservar exatamente os formatos textuais atuais. Evitar base64 no envelope para arquivos grandes; não interpretar um prefixo de texto comum como binário.
- A entrada deve estar em área de staging autorizada por tentativa e ser aberta com tratamento de symlink, traversal e substituição concorrente. Usar descritor já aberto, verificar arquivo regular, tamanho e hash durante cópia limitada por fluxo; nunca confiar em caminho ou hash fornecidos pelo agente sem verificação. Definir portabilidade Windows/Linux e falhar fechado se as garantias não estiverem disponíveis.
- Validar destinos e limites antes de qualquer efeito final. Copiar para staging privado do Orchestrator, com limpeza em falha, fsync e publicação atômica; garantir que o conteúdo validado seja o conteúdo aplicado. A gravação do evento e os efeitos devem respeitar a semântica transacional existente; testar interrupções entre fases.
- Guardar blobs endereçados por conteúdo em repositório de artefatos do Orchestrator, com SHA-256, bytes, formato/versão e referência no evento. Não incorporar bytes grandes ao JSONL. A recuperação valida hash e tamanho antes da aplicação, preserva boundaries e produz o mesmo conteúdo. Definir retenção, contabilização de espaço e coleta segura que nunca exclua blobs necessários ao replay/recovery; ausência ou corrupção deve produzir erro explícito, sem declarar sucesso.
- `dry-run` deve validar schema, limites, caminhos, disponibilidade e integridade sem gravar eventos ou efeitos finais; especificar e testar se utiliza espaço temporário. Tratar destino existente, permissões, espaço insuficiente, hard links, troca de diretório, concorrência e conflito de escrita.

## Mudanças e sequência planejadas

1. **Contrato e migração**: especificar schema do efeito, limites por tarefa, evento administrativo, compatibilidade de versão e matriz de segurança. Evoluir templates, projetor e schemas de roadmap e agente; fornecer migração seletiva, idempotente e verificável dos contratos ativos. Não usar `bootstrap --force` como migração genérica, pois substitui todo o bundle de governança.
2. **Criação e limites**: alterar [[task_creation.py|criação]], CLI, validação, projeção, `state`/dispatch e alteração auditada em andamento. Manter defaults e replay dos eventos antigos; assegurar limites efetivos também no fluxo de submissões múltiplas e efeitos externos.
3. **Staging e artefatos**: implementar transporte binário por fluxo, armazenamento content-addressed, metadados, commit atômico, recovery, limpeza, limites e integração com [[submission.py|submissão]]. Manter compatibilidade de artefatos textuais antigos.
4. **Verificação**: testes unitários e de integração para PNG e MKV reais, arquivo acima de 2 MiB, fronteiras exatas e excedidas, múltiplos efeitos, total, quota, symlinks/traversal, troca de origem/destino, permissões, colisão, concorrência, interrupção, rollback, dry-run, corrupção, ausência de blob, recovery, replay e compatibilidade textual. Teste grande por streaming deve comprovar memória limitada, sem depender apenas de mocks.
5. **Distribuição e migração controlada**: exercitar atualização e reversão em cópia isolada de workspace real; preservar contratos locais, eventos e projeções. Só instalar/ativar versão após suíte e verificação passarem. Verificar o pacote realmente carregado por `python -m esaa`, a política efetiva e `verify` antes de qualquer tarefa PTB. Nenhuma publicação externa está implícita.
6. **Retomada PTB**: migrar o workspace sem destruir configurações; registrar limites da ML02 por evento administrativo específico e verificar o boundary existente. Reexecutar evidência PNG/FFV1, aplicar pelos efeitos do Orchestrator, conferir bytes, SHA-256, ffprobe e recovery em cópia isolada. Resolver ISS-PTB-BINARY-EFFECTS-20261102 somente após prova; executar review e verify e seguir as próximas tarefas elegíveis. Os limites de outras tarefas também deverão ser declarados antes de sua execução.

## Critérios de aceite

- Criação, projeção, dispatch e replay preservam limites declarados e defaults históricos; ultrapassagens são rejeitadas com erro claro, sem efeitos parciais.
- Um binário maior que 2 MiB é aplicado e recuperado com hash e bytes idênticos dentro de limites autorizados; uma cópia corrompida ou fora do limite é rejeitada.
- Efeitos antigos de texto e artefatos antigos continuam verificáveis e recuperáveis; boundaries, concorrência, identidade de runner e transações permanecem efetivos.
- ML02 só chega a `done` depois de execução, verificação e revisão reais. Estar com a especificação ou os testes do núcleo aprovados não comprova fidelidade integral do showreel nem homologação Craft.

## Governança e estado

O planejamento está registrado pela tarefa CORE-BINARY-PLAN-20261102. CORE-BINARY-FILE-EFFECTS-20261102 permanece em andamento e concentra a implementação; ISS-CORE-BINARY-RESOURCE-CONTRACT-20261102 permanece aberta. Este plano não cria automaticamente etapas executáveis adicionais nem afirma que o núcleo foi modificado. A decomposição em tarefas governadas e os detalhes da migração deverão ser registrados antes da implementação correspondente.

## Referências

**Este documento referencia:** [[agent_result.schema.json|schema ativo]], [[file_effects.py|efeitos de arquivo]], [[validator.py|limites]], [[task_creation.py|criação de tarefas]] e [[submission.py|submissão]].

**Este documento é referenciado por:** nenhuma referência documental identificada nesta sessão.
