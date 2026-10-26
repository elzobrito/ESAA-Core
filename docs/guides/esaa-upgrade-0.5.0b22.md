# Atualização ESAA — 0.5.0b22

🌐 **Português** · [English](esaa-upgrade-0.5.0b22.en.md)

Estado em 26/10/2026: **release 0.5.0b22**. Protocolo 0.4.2, armazenamento 0.4.1. A publicação no PyPI não ativa identidade; o bootstrap continua sendo etapa do proprietário. Confirme o SHA256 público antes de atualizar instalações operacionais.

## Mensagem para o Grok e o Antigravity

ESAA é um protocolo local de governança por eventos. O pacote é `esaa-core`, o módulo é `esaa`; não há servidor MCP ESAA. O agente propõe resultados; o Orchestrator valida contratos, registra eventos e aplica efeitos. `.roadmap/activity.jsonl` é a fonte de verdade. Projeções são reconstruídas e nunca devem ser corrigidas manualmente.

O Grok pode coordenar e o Antigravity pode executar uma tarefa delimitada. O runner registrado deve representar o executor real; o actor é a identidade/papel autorizado, não o nome do modelo. Trocar de modelo não transfere ownership nem concede permissões.

1. Inspecione `python -m esaa --root /caminho/projeto eligible` e os contratos locais.
2. Crie tarefas autossuficientes antes de implementar: contexto, dependências, saídas, limites e critérios de aceite. Use a ajuda da versão instalada para cada comando.
3. Entregue ao auxiliar `dispatch-context TASK-ID` e recupere as referências necessárias. A lista inteira do backlog não substitui esse contexto.
4. Faça `claim` e depois `complete` em submissões separadas. O mesmo actor completa; efeitos finais seguem em `file_updates` no complete. Identifique o runner real em toda escrita.
5. Encaminhe a revisão ao papel autorizado. `review` precede `done`; `done` é terminal. Falhas posteriores exigem issue/hotfix.
6. Execute `verify` após escritas governadas. Integridade estrutural, testes, revisão e publicação são evidências diferentes.

## Lacunas relatadas e comportamento atual

- **Arquivo na raiz:** `scope_patch` restringe caminhos; não concede escrita. `hotfix create` suporta `--boundary-grant`, `--output` e `--executable-check`. Autorize explicitamente o arquivo necessário, por exemplo `tetris.py`, segundo o contrato. Não mova arquivos só para contornar limites.
- **Hotfix duplicado:** `issue report --fixes` já cria o hotfix. Escolha esse fluxo ou reporte a issue e crie o hotfix separadamente. Não execute ambos para o mesmo vínculo.
- **Eventos verify:** pares de eventos de verificação são parte do histórico de comandos que escrevem. A proporção no log não mede, sozinha, desperdício ou defeito. Preserve o histórico; use `activity list` para consultas.
- **Checks de complete:** checks textuais continuam declarações. A extensão opcional de verificação executável roda checks em Docker isolado quando habilitada/configurada pelo operador. Não converte texto em execução automaticamente. A evidência fica vinculada ao candidato, tarefa, actor e ciclo; alteração invalida sua reutilização.
- **Listagem:** use `task list` e a ajuda dos filtros/paginação. `eligible` mostra tarefas disponíveis, não todo o backlog.
- **Chain e métricas:** consulte `chain --help` antes de inicializar uma cadeia; uma cadeia válida sem âncora externa tem garantias limitadas. Use `runner metrics`; `attempts_total` conta rejeições, não todas as execuções.

A b21 preserva replay de escopos absolutos históricos e emite `LEGACY_SCOPE_PATCH_UNSAFE`; novas escritas continuam rejeitando escopos inseguros. Evite b20 em stores afetados. A b22 acrescenta correções de tipagem, staging, aliases e proteção da identidade descritas no [modelo de ameaças](../security/threat-model.md). Revisões `qa_role` dos hotfixes de identidade estão no closeout; o contrato de identidade permanece inactive. Residuais: provisionamento do owner, persistência do scanner (`BLOCKED_STORAGE`) e o auditor automático de cibersegurança.

## Atualização após liberação

Confirme primeiro a aprovação do commit exato, CI e publicação PyPI com hashes correspondentes. Preserve uma cópia do workspace e dos registros externos do proprietário. Atualize cada ambiente que realmente usa ESAA, sem misturar instalações inadvertidamente:

```bash
# Depois de conferir os hashes públicos de esaa-core==0.5.0b22:
python -m pip install --upgrade 'esaa-core==0.5.0b22'
# Para instalação administrada por pipx:
pipx upgrade esaa-core
python -m esaa --version
esaa --version
python -m esaa --root /caminho/projeto verify
```

Em Python administrado pelo sistema, use um ambiente virtual ou pipx; não force a quebra da proteção do sistema. `pipx upgrade` instala a versão permitida pelo spec original: confirme que resolveu exatamente b22. Compare o Python de usuário, o executável no PATH e o ambiente pipx. Faça um smoke isolado antes do workspace real. As evidências locais de wheel/sdist são provisórias e não comprovam publicação PyPI.

## Identidade: ativação é uma etapa do proprietário

A atualização não deve executar bootstrap, gerar chaves definitivas ou ativar identidade automaticamente. Sem ativação, o modo legado não comprova identidade criptográfica. Após ativação, operações protegidas exigem assinaturas Ed25519 e regras de identidade canônica; aliases do mesmo principal não são revisores independentes.

O candidato usa pin `esaa.identity.trust.v2`, compromisso do histórico completo, checkpoint serializado e intenção de ativação persistida antes do primeiro append. O enrollment público é descoberto pelo perfil do usuário do sistema operacional, fora do workspace, independentemente de HOME/XDG e de `ESAA_TRUST_ROOT`. A localização do trust root precisa coincidir com esse enrollment. O proprietário deve impedir escrita do agente nesses registros: permissões 0700 com agente no mesmo UID não criam isolamento.

O owner prepara o pin por meio da API `make_pin(public_key_hex=...)`, protege chaves privadas fora dos artefatos e prepara autorizações assinadas conforme o contrato. A CLI oferece `actor trust-import --pin ARQUIVO`, `actor bootstrap --authorization ARQUIVO --dry-run`, `actor register`, `actor bind-alias` e `--authorization` nas operações protegidas. Não existe comando `trust-pin template`. Consulte a ajuda antes de qualquer ativação real e satisfaça o gate de pré-ativação.

Pin v1 não é convertido automaticamente em v2. Migração exige decisão e referência confiável do proprietário. Não apague enrollment/checkpoint nem reconstrua a confiança a partir da réplica do projeto para superar uma falha. Não faça downgrade após eventos de identidade/aliases ou pin v2 sem plano validado de compatibilidade e recuperação. Uma falha parcial de bootstrap deve permanecer bloqueada para recuperação pelo proprietário.

## Evidência e retomada

Os testes do implementador passaram em 597 casos; staging e empacotamento tiveram revisão independente específica. Isso não conclui a revisão de identidade. O scanner histórico preserva seu snapshot; o complemento não pode ser apresentado como resultado daquele scan. Veja o [relatório de impedimentos](../qa/closeout-20261026/hotfix-review-input.md) e os [artefatos de distribuição](../qa/actor-registration/packaging/README.md).

A revisão automática bloqueou a continuação do auditor de identidade por possível risco de cibersegurança. O armazenamento do scanner também continua rejeitando a persistência. Portanto: não há READY_FOR_OWNER_BOOTSTRAP, release b22 ou autorização de ativação. Para retomar, conclua a revisão independente permitida, resolva a cobertura/armazenamento e cumpra QA004 e os gates de release. Nenhum token PyPI foi lido nesta preparação.
