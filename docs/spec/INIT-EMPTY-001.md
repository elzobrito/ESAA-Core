# INIT-EMPTY-001 — Init com roadmap vazio por default

## Objetivo

Fazer `esaa init` nascer **sem** a trilha demo `T-1000` / `T-1010` / `T-1020`.
Seeds de demonstração só sob flag explícita.

## Decisão de produto

| Modo | Comportamento |
|------|----------------|
| **Default** | `init` cria run + lessons baseline + verify; **lista de tasks vazia** (exceto seeds de plugin ativo). |
| **Demo** | `init --with-demo-tasks` inclui `seed_tasks()` (`T-1000`→`T-1010`→`T-1020`). |
| **Plugin** | Se houver roadmap de plugin ativo, usa as tasks do plugin (**ignora** demo seeds; flag demo não mistura). |

### CLI

```bash
python -m esaa --root . init
python -m esaa --root . init --force
python -m esaa --root . init --with-demo-tasks
python -m esaa --root . init --force --with-demo-tasks
```

### API Python

```python
ESAAService(root).init()
ESAAService(root).init(force=True)
ESAAService(root).init(with_demo_tasks=True)
ESAAService(root).init(force=True, with_demo_tasks=True)
```

## Interações

### Onboard / GOV-PROFILE

- Após `init` vazio, `onboard` cria `GOV-PROFILE-*` sem precisar supersede de seeds.
- Se `init --with-demo-tasks` + `onboard`, mantém-se a semântica atual de `supersedes` T-1000/1010/1020 quando esses ids existem em `todo`.

### activity clear --force

- Clear reseed de lessons **não** reintroduz T-1000; roadmap fica sem tasks de demo.
- Operador que quiser demo de novo: `init --force --with-demo-tasks` (ou criar tasks manualmente / onboard).

### Plugins

- `load_plugin_seeds` continua prioritário: tasks do plugin substituem o branch demo/vazio.

## Critérios de aceite

1. `init` sem flag → zero tasks `T-1000`/`T-1010`/`T-1020` no roadmap.
2. `init --with-demo-tasks` → trilha demo presente e elegível (T-1000).
3. Testes automatizados cobrem ambos os modos; suite existente usa demo flag onde depende de T-1000.
4. README/help documentam o default vazio e a flag.

## Plano de testes

- Unit/CLI: empty vs demo vs plugin precedence.
- Regressão: pytest completo com `with_demo_tasks=True` nos fixtures legados.
- Manual: bootstrap → init → eligible vazio de seeds; init --with-demo-tasks → eligible T-1000.

## Fora de escopo

- Remover `seed_tasks()` do código (permanece para demo/flag).
- Mudar schemas G07 do roadmap local.
- Release PyPI (pode ser release separada).
