# Contributing

Contributions are welcome when they preserve the ESAA model: the event store is
append-only, read models are projections, and the Orchestrator is the only
authority that applies state transitions.

Before proposing a change, run the local test suite:

```powershell
$env:PYTHONPATH='src'
python -B -m pytest -q
python -B -m esaa --root . verify
```

For plugin changes, also check:

```powershell
$env:PYTHONPATH='src'
python -B -m esaa --root . plugin list --available
```

Keep changes small, documented, and covered by tests when behavior changes.

