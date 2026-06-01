# ESAA Plugin Lifecycle

Plugin lifecycle and roadmap execution lifecycle are separate.

Install a plugin package:

```powershell
python -m esaa --root . plugin install ./plugins/security
```

Activate a roadmap execution:

```powershell
python -m esaa --root . roadmap activate security --execution-id default
```

The active execution exposes tasks with dash-based ids:

```text
security-default-T-001
```

Pause or resume without uninstalling:

```powershell
python -m esaa --root . roadmap pause security --execution-id default
python -m esaa --root . roadmap resume security --execution-id default
```

Deactivate removes the execution from new eligibility:

```powershell
python -m esaa --root . roadmap deactivate security --execution-id default
```

Remove uninstall state:

```powershell
python -m esaa --root . plugin remove security
```

The plugin directory still contains `plugin.json` and `roadmap.template.json`;
the workspace lock files only record what is installed and active.

