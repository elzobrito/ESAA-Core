# Modelo de ameaças — identidade e efeitos ESAA

🌐 **Português** · [English](threat-model.en.md)

## Estado e escopo

Candidato 0.5.0b22, protocolo 0.4.2, armazenamento 0.4.1. Revisão independente de identidade pendente: **BLOCKED_EVIDENCE**. Este documento descreve desenho e testes observados, sem certificar segurança em produção. Consulte o [guia de atualização](../guides/esaa-upgrade-0.5.0b22.md) e a [evidência](../qa/closeout-20261026/hotfix-review-input.md).

## Ativos e autoridades

Protegem-se histórico, projeções, ownership de tarefas, autorização de revisão, boundaries e bytes finais dos efeitos. O Orchestrator valida e escreve; o runner declara proveniência operacional e não substitui identidade criptográfica. No modo legado, os nomes de actor seguem a política local, mas não provam posse de chave. Autenticação Ed25519 é uma extensão com ativação explícita; os antigos exemplos HMAC/identity.strict não descrevem este protocolo.

O proprietário controla a autoridade bootstrap, pin externo e enrollment do host. O agente controla propostas e candidatos, não deveria controlar esses registros externos nem chaves do proprietário. O processo do Orchestrator, sistema operacional, implementação criptográfica e configuração autorizada são parte da base confiável.

## Controles e evidências por ameaça

| Ameaça | Controle implementado no candidato | Limite/evidência |
|---|---|---|
| Credencial inválida descartada no registry inativo | Operação com authorization não nula exige bootstrap; None preserva legado | Testes do implementador; revisão final pendente |
| Alias usado para autoaprovação ou colisão de identidade | Principal canônico para ownership/review; colisão inversa actor/alias rejeitada | Testes API/CLI/replay; revisão final pendente |
| Rollback do projeto ou perda/troca de ESAA_TRUST_ROOT | Enrollment público descoberto pelo perfil OS; raiz/fingerprint externos vinculados ao workspace | Exige isolamento real do proprietário; revisão final pendente |
| História reescrita com cadeia recalculada | Pin v2 compromete prefixo completo do histórico, além das projeções | Cadeia sem âncora externa não basta; revisão final pendente |
| Checkpoints concorrentes regressivos | Leitura/validação/escrita sob lock de registro; ordem store → pin | Teste determinístico concorrente; revisão final pendente |
| Crash na ativação antes do checkpoint | Intent durável antes do primeiro append, ligado aos eventos planejados | Interrupção falha fechada; recuperação cabe ao proprietário |
| Troca de bytes entre verificação e aplicação | Commit recompõe temporário a partir do conteúdo validado em memória; nomes exclusivos, replace atômico e modo preservado | Revisão independente repetiu adulteração e concorrência; passou |
| Candidato alterado reutiliza execução | Evidência executável vinculada a tarefa/actor/ciclo/configuração/inputs/candidato | Docker isolado opcional; declarações textuais não viram execução |

Assinaturas, sequência e regras de replay são validadas antes de aceitar efeitos. O lock de armazenamento coordena escritores; não é uma autorização adicional. Nunca remova locks manualmente. Falhas de integridade exigem interrupção e diagnóstico, não edição do log.

## Fronteiras e não garantias

`ESAA_TRUST_ROOT` sozinho não constitui confiança independente. O enrollment Unix usa o home obtido por UID no sistema; Windows usa a pasta LocalAppData do perfil OS. HOME/XDG não selecionam esse registro. Tanto enrollment quanto trust root precisam ficar fora do workspace e inacessíveis para escrita pelo agente. Um agente com o mesmo UID pode ter acesso apesar de modo 0700. Comprometimento do host, owner ou processo confiável não é resolvido por esse desenho.

Não há conversão automática de pins v1 para v2, bootstrap automático ou permissão para reconstruir confiança usando somente a réplica controlada pelo projeto. Os testes usam fixtures descartáveis; nenhum bootstrap real foi realizado neste trabalho. A cadeia do Core sem âncora externa e a extensão de execução desabilitada por padrão não implicam ativação: são estados opcionais que devem ser apresentados corretamente.

A política local controla quem pode revisar; um nome/alias de QA e um teste passando não substituem revisão independente. O scanner histórico cobre apenas seu snapshot. A revisão complementar dos novos bytes de identidade não terminou; o gate de release permanece fechado.
