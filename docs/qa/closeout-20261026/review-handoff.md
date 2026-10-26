# Checkpoint para revisão — 26/10/2026

**BLOCKED_EVIDENCE. Candidato b22 não publicado.** Este checkpoint entrega código, testes, documentação e estado governado para revisão; não encerra o plano de release.

## Entregas

- Correção de tipagem sem relaxar validação.
- Aplicação dos bytes validados em memória com temporários exclusivos; adulteração de staging não altera o efeito final. Revisão independente específica passou em 48 testes, incluindo duas reproduções com Docker.
- Correções candidatas de identidade: autorização não nula recusada em modo inativo, colisão inversa actor/alias recusada, enrollment por perfil OS, compromisso de histórico completo, checkpoint serializado e intenção durável pré-append. Permanecem em review independente.
- Wheel/sdist locais instalados em ambientes limpos, com metadados, bytes e dependências conferidos independentemente. Cada smoke sintético executou Docker, tarefa/hotfix e verify/chain. Artefatos são provisórios: publicação final exige rebuild e hashes do commit aprovado.
- Guias PT/EN para o Grok e modelo de ameaças atualizados. A máquina opera com b21 no Python de usuário e pipx, removendo a divergência pipx b19. Nenhuma instalação operacional b22 ou ativação real.

## Validação e atribuição

O implementador executou 597 testes com Docker habilitado (85,74 s), mypy sem erros em 58 módulos e lint/formatação no escopo CI. Após as alterações documentais, 41 testes de distribuição dos guias/beta passaram. Revisores independentes aprovaram a correção de tipagem, staging e empacotamento nos respectivos escopos. A revisão de identidade anterior às últimas correções encontrou falhas; a revisão dos bytes corrigidos não foi concluída.

`verify` passou no Core e no workspace /home/elzobrito. O histórico original de 8dce320, com 753956 bytes, foi preservado como prefixo byte a byte. O aviso histórico LEGACY_SCOPE_PATCH_UNSAFE no workspace home foi preservado. Não foram criadas chaves definitivas, pin vivo ou bootstrap; TCG não foi modificado. O arquivo de token PyPI não foi lido.

## Tarefas e impedimentos

Concluídas: BASE, TYPE, EVID, ALIGN-STABLE, packaging existente e hotfix de staging. DOCS e HANDOFF encerram somente suas entregas específicas após validação. Permanecem:

- ESAA-HF-ACTOR-TRUST-ROLLBACK-002: review.
- ESAA-HF-ACTOR-CANONICAL-IDENTITY-003: review.
- HF-ISSUE-ESAA-SIGNED-REPLAY-POSTFIX-REVIEW-001: review.
- ESAA-CLOSE-20261026-SCAN: in_progress, bloqueado por evidência.
- ESAA-QA-ACTOR-PREACTIVATION-004: todo, depende das revisões legítimas.
- ESAA-CLOSE-20261026-ISSUES, RELEASE e INSTALL: todo, dependências preservadas.

Issue ISS-ESAA-CLOSE-INDEPENDENT-REVIEW-20261026 registra os impedimentos. A continuação do auditor independente de identidade foi rejeitada automaticamente por possível risco de cibersegurança. Essa avaliação não foi repetida em outra instância para contornar o bloqueio. O scanner histórico cfe966df-2ad4-4d14-9f2d-c7354bf49a6d mantém seu snapshot. Preflight passou; a persistência continua rejeitada com `Scan output parent must not be group- or world-writable without the sticky bit.` O chmod pontual autorizado não resolveu; nenhuma alteração ampla de permissões foi aplicada.

## Como retomar

1. Concluir a revisão independente de identidade por mecanismo autorizado e disponível, vinculada aos hashes finais; não substituir por testes do implementador ou aprovação textual por alias.
2. Resolver a persistência/cobertura do scanner sem modificar seu snapshot histórico. Registrar separadamente o complemento atual.
3. Concluir hotfixes legitimamente e só então reivindicar QA004, mantendo todos os artefatos e critérios exigidos.
4. Reconciliar issues por causa/evidência; executar CI do commit exato, rebuild, release PyPI com hashes públicos e instalação exata da versão publicada.
5. Manter ativação real como decisão separada do proprietário, com isolamento externo efetivo; nunca apagar registros de confiança para superar uma rejeição.

## Para o Grok

Continue na versão pública b21 enquanto b22 está em revisão. Consulte o [guia completo em português](../../guides/esaa-upgrade-0.5.0b22.md) ou [inglês](../../guides/esaa-upgrade-0.5.0b22.en.md). Eles explicam tarefa/dispatch/claim/complete/review, hotfix/grants, checks textuais e Docker, consultas, métricas e o procedimento de atualização somente após publicação confirmada. Os comandos de instalação b22 nesses guias são condicionais, não uma declaração de disponibilidade.

Evidências detalhadas: [matriz e bloqueios](hotfix-review-input.md), [distribuição](../actor-registration/packaging/README.md), [instalação estável](stable-install.json). Este resultado deve ser commitado e enviado em branch de revisão `codex/esaa-closeout-20261026`, sem tag de release ou publicação na main/PyPI. O resultado remoto e CI são reportados na mensagem de entrega, pois só existem após este registro.
