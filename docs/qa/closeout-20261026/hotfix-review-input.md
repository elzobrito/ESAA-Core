# Fechamento técnico — evidência e impedimentos

Data: 26/10/2026. Candidato local 0.5.0b22. **BLOCKED_EVIDENCE**: não há parecer READY_FOR_OWNER_BOOTSTRAP nem publicação da b22.

## O que foi executado

Baseline e tarefas foram registrados antes das mudanças. A tipagem foi corrigida e passou na revisão independente. O candidato final passou em **597 testes em85,74s**, com Docker habilitado, mypy sem erros nos58módulos e lint/formatação no escopo CI. Os26testes adicionais exercitam falhas que os571testes anteriores não cobriam.

A revisão independente inicial encontrou quatro lacunas de confiança externa, descarte de autorização no modo legado, colisão inversa actor/alias e divergência entre staging e candidato verificado. As reproduções anteriores, controles e hashes estão em hotfix-review-input.json. Todas ocorreram em fixtures descartáveis; nenhum estado vivo foi adulterado.

## Entregas e revisões

A falha de staging foi corrigida, reavaliada independentemente e encerrada em HF-ISS-ESAA-STAGED-CANDIDATE-20261026. O revisor repetiu as duas reproduções: bytes finais exatos e duas submissões concorrentes sem colisão. Verificou também permissões existentes, remoção de temporários e48testes pertinentes. O commit reconstrói o arquivo a partir do conteúdo validado em memória; a cópia mutável do staging não decide os bytes finais.

As correções de identidade foram entregues **para review**:002 protege descoberta estável do enrollment, histórico completo, serialização do checkpoint e intent persistente antes do primeirobootstrap;003 rejeita colisão deactor comalias; o hotfix de postfix rejeita credencial fornecida em registryinativo, preservando authorization=None legítimo. A continuidade do auditor de identidade foi bloqueada pela avaliação automática por possível risco de cibersegurança. Não substituímos esse parecer por autorrevisão nem encaminhamos a mesma avaliação a outra instância para contornar o bloqueio. Os testes do implementador não constituem aprovação independente.

## Scanner histórico e cobertura

O scan cfe966df-2ad4-4d14-9f2d-c7354bf49a6d permanece running/discovery sobre seu snapshot histórico. O preflight atual passou nos3checks; a atualização foi recusada por fase já avançada. O ajuste pontual autorizado do pai ESAA-Core foi aplicado0775→0700, sem recursão. A tentativa de persistência ainda retornou `Scan output parent must not be group- or world-writable without the sticky bit.` Não ampliamos permissões/configs, não forçamos conclusão e não atribuímos coberturaatual ao snapshotantigo.

A auditoria terminal complementar inspecionou os módulos de identidade, runtime de verificação, queries, grants e integrações. A revisão posterior do staging está completa. A revisão dos novos bytes de identidade permanece pendente; portanto a cobertura global atual é parcial e o gate de segurança continua bloqueado.

## Distribuição e operação

Wheel e sdist locais passaram twinecheck e instalação limpa fora do checkout; cada instalação executou o ciclo sintético Docker, tarefa/hotfix done e verify/chainok. Isso comprova empacotamento/runtime observado, sem autorizar ativação criptográfica. Consulte ../actor-registration/packaging/reconciliation.json para hashes e evidências.

A versão pública operacional continua b21. O pipx foi alinhado à b21 para remover a cópia b19; o Python de usuário permaneceu b21. A b22 não foi instalada como runtime operacional nem publicada. O token PyPI não foi lido. Nenhuma chave definitiva, pin vivo ou bootstrap real foi criado; TCG e histórico foram preservados.

## Condições para retomar

1. Obter revisão independente autorizada dos hashes finais de identidade, com disponibilidade do mecanismo de avaliação apropriado; nenhuma aprovação por alias ou papel textual substitui isso.
2. Resolver ou documentar definitivamente armazenamento/cobertura do scanner, preservando o scanoriginal e distinguindo o complemento.
3. Só após002/003 e packaging done legítimos, reivindicar QA004 e emitir seu parecer integrado. Não reivindicar antecipadamente nem enfraquecer dependências.
4. Reconciliar issues por evidência; depois concluir release com CI do commit exato, PyPI com hashes públicos e instalação da versão publicada. Identidade real continua decisão separada do proprietário.
