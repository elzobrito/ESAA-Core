# ESAA — Event Sourcing for Autonomous Agents

ESAA é um protocolo de governança para engenharia de software com agentes.
O agente propõe intenções; o Orchestrator valida e aplica efeitos; o histórico
append-only permite reconstruir o estado e auditar cada transição.

```text
Agent proposes -> Orchestrator validates -> Event store records -> Projection updates
```

Este repositório contém o runtime Python `esaa-core`, contratos, templates e testes.
O ESAA não usa MCP. `.roadmap/activity.jsonl` é a fonte da verdade; as projeções
não são editadas manualmente.

## Quickstart

```bash
python -m pip install --upgrade --pre esaa-core
python -m esaa --version
mkdir esaa-demo
cd esaa-demo
python -m esaa bootstrap --profile public
python -m esaa --runner codex init
python -m esaa verify
python -m esaa eligible
```

Use o runner real no lugar de `codex`. Um workspace novo começa sem tarefas;
`eligible` vazio é normal. `verify_status: ok` confirma consistência com replay.
Consulte `python -m esaa task create --help` para criar uma tarefa.

`bootstrap` instala contratos e guias portáteis. Não altera histórico ou projeções.
Em projetos existentes, escolha explicitamente preservar ou mesclar guias;
`--force` sobrescreve os arquivos permitidos. Detalhes na referência CLI.
Nenhum desses comandos autoriza publicação. O pacote permanece em beta.

## Documentação sob demanda

| Necessidade | Referência |
| --- | --- |
| Começar e configurar o projeto | [Primeiros passos](docs/guides/esaa-getting-started.md) · [English](docs/guides/esaa-getting-started.en.md) |
| Entender o modelo e quando usar | [Por que ESAA](docs/guides/esaa-why.md) · [English](docs/guides/esaa-why.en.md) |
| Trabalhar com Codex ou Claude Code | [Runners](docs/guides/esaa-runners-codex-claude-code.md) · [English](docs/guides/esaa-runners-codex-claude-code.en.md) |
| Operações, arquitetura e recuperação | [Referência CLI](docs/guides/esaa-cli-reference.md) · [English](docs/guides/esaa-cli-reference.en.md) |
| Exemplos de uso | [Cenários](docs/guides/esaa-cenarios.md) · [English](docs/guides/esaa-cenarios.en.md) |
| Plugins | [Autoria](docs/plugins/authoring.md) · [Instalação](docs/plugins/installing.md) · [Ciclo](docs/plugins/lifecycle.md) · [Segurança](docs/plugins/security.md) |
| Modelo de ameaças | [Português](docs/security/threat-model.md) · [English](docs/security/threat-model.en.md) |
| Contribuir com o Core | [AGENTS.md](AGENTS.md) · [CONTRIBUTING.md](CONTRIBUTING.md) |

Os guias do repositório explicam o Core; os guias empacotados atendem projetos
consumidores e não precisam ser cópias deste README. Os perfis PARCER são
referências por papel, sem leitura obrigatória de todos os perfis.

## Desenvolvimento

No checkout, use a fonte local para evitar importar uma instalação antiga:

```bash
PYTHONPATH=src python -B -m esaa --help
PYTHONPATH=src python -B -m pytest -q
PYTHONPATH=src python -B -m esaa --root . verify
```

Mudanças de comportamento exigem evidência proporcional; veja CONTRIBUTING.
Não há aprovação de release implícita no sucesso dos testes locais.

## Referência acadêmica e licença

[Artigo ESAA](https://arxiv.org/pdf/2602.23193).

```bibtex
@article{santos2026esaa,
  title={ESAA: Event Sourcing for Autonomous Agents in LLM-Based Software Engineering},
  author={Santos Filho, Elzo Brito dos},
  year={2026},
  note={Preprint}
}
```

MIT. Autor: Elzo Brito dos Santos Filho.
