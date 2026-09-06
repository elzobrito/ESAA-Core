# Release 0.5.0b19 — evidências finais

Data: 2026-09-05. Status: pré-release publicada e instalação pública validada.

Este relatório atualiza a situação de release registrada em GUIDE-20260905.md,
preservado como evidência histórica. Não declara uma versão estável.

## Fonte e publicação

- Commit publicado: `4b7cd7a05f93cca2dd326027991a2b0df9d6315c`.
- Tag e release: https://github.com/elzobrito/ESAA-Core/releases/tag/v0.5.0b19
- CI: https://github.com/elzobrito/ESAA-Core/actions/runs/33984077549
- Publicação: https://github.com/elzobrito/ESAA-Core/actions/runs/33984152601
- Distribuição: https://pypi.org/project/esaa-core/0.5.0b19/

Os dois workflows terminaram com success no commit indicado. A primeira tentativa
de publicação falhou por invalid-publisher; a execução posteriormente concluída
publicou os artefatos. Nenhuma configuração de credenciais foi alterada pelo agente.

## Validação

- Preparação local registrada em REL-0.5.0B19-PREP: 415 testes passaram no candidato
  isolado, sem incorporar alterações preexistentes de plugins.
- CI hospedada: testes Python 3.11, 3.12 e 3.13 e lint passaram.
  Typecheck falhou, sendo explicitamente não bloqueante no workflow vigente;
  portanto não se afirma que todos os jobs individuais passaram.
- Instalação nova em ambiente temporário fora do checkout, Python 3.14, diretamente
  de https://pypi.org/simple, sem cache: esaa-core==0.5.0b19 instalado com sucesso.
- Com esse pacote público, bootstrap public e production, init, eligible e verify
  passaram em dois workspaces temporários. Ambos terminaram em verify_status=ok,
  sequência 4 e zero tarefas elegíveis, coerente com inicialização vazia.
- Workspace /home/elzobrito: CLI 0.5.0b19 e verify_status=ok, sequência 4176,
  hash f2b933fcf79adf822ac1607270f8618aca5b9ad0edc7f286f904eca19f0f19a2.
- Core antes do fechamento: verify_status=ok, sequência 815.

## Rastreabilidade e limites

A pendência ISS-GUIDE-20260905-BASELINE-EVIDENCE foi tratada pelo hotfix
HF-ISS-GUIDE-20260905-BASELINE-EVIDENCE. O vínculo de resolução foi acrescentado
ao histórico, sem reabrir tarefas done, reescrever eventos ou enfraquecer o auditor.
A suíte hospedada passou com o teste de rastreabilidade preservado.

As alterações alheias em src/esaa/plugins.py, tests/test_plugin_manager.py e
docs/operations/create-workflow-esaa-core.md permanecem fora desta entrega.
A aprovação de QA usa o papel autorizado agent-qa no mesmo runner codex;
não representa revisão humana ou independente.

## Artefatos públicos

- `esaa_core-0.5.0b19-py3-none-any.whl`: SHA-256 `c63500a5b80d14ec42f435a94984cae11ef074454c90062fafd01c0b6426aa3c`
- `esaa_core-0.5.0b19.tar.gz`: SHA-256 `af94c3d07277dd003cf147fa46e72bb32651f1f2bb1df79e1fd372516b5b952a`
