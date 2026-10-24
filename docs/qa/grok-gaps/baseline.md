# Baseline das lacunas Grok

Workspace: /home/elzobrito/desenvolvimento/ESAA-Core.

Em 24/10/2026, o checkout apresentava alterações anteriores de identidade, atores e replay assinado. Elas foram copiadas integralmente para o candidato; o diff e hashes iniciais estão em /tmp/esaa-grok-ng2vtrjq. Nenhuma dessas alterações foi revertida.

Baseline: `PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider`: **477 passed in 42.26s**. Docker Server 29.1.3 disponível; identidade do workspace inativa e verify ok antes do trabalho (seq 958).

Plano: hotfix com grants explícitos; consultas read-only; catálogo opcional de verificação em Docker; evidências vinculadas; documentação PT/EN; QA e pacote em ambiente limpo.

Fronteiras: não alterar Tetris original, não publicar, não instalar globalmente, não herdar grants, não apagar eventos verify. Protocolos e schemas novos devem manter leitura do legado e assinaturas históricas. O runtime do checkout será invocado com PYTHONPATH=src.

Tarefas ESAA-GROK-20261024-001 a 008 registram contexto, dependências, outputs absolutos, aceite e exclusões. O schema ativo legado não comporta acceptance_criteria; critérios estão nas descrições.
