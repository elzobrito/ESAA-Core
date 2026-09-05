# ESAA neste projeto

Este workspace usa ESAA para governança de agentes: agentes emitem intenções,
o Orchestrator valida e aplica efeitos, e `.roadmap/activity.jsonl` é a fonte
da verdade. Consulte [AGENTS.md](AGENTS.md) para trabalhar neste projeto.

Se o runtime ainda não estiver instalado:

```bash
python -m pip install --upgrade --pre esaa-core
python -m esaa --version
```

Após o bootstrap, inicialize somente um workspace ainda não inicializado:

```bash
python -m esaa --runner codex init
python -m esaa verify
python -m esaa eligible
```

Substitua `codex` pelo runner real. Sem tarefas cadastradas, `eligible` vazio
é esperado. Para uma tarefa existente, use `python -m esaa dispatch-context TASK-ID`.
A sintaxe de criação está em `python -m esaa task create --help`.

Os [contratos locais](.roadmap/AGENT_CONTRACT.yaml) e a
[política de runtime](.roadmap/RUNTIME_POLICY.yaml) regem execução e revisão.
Não edite o histórico nem as projeções manualmente. `verify: ok` confirma
consistência; não autoriza publicação ou implantação.

## Contexto do projeto

Documente aqui o propósito e as referências específicas deste projeto.
