# ESAA Plugin Installing

Plugins can be installed from a local directory, from an external catalog, or
from a bundled plugin id when the distribution includes bundled plugins. In all
cases the package must be a folder with `plugin.json` and
`roadmap.template.json`.

Local directory plugin:

```powershell
python -m esaa --root . plugin new security
python -m esaa --root . plugin validate ./security
python -m esaa --root . plugin install ./security
```

External catalog plugin:

```powershell
python -m esaa --root . plugin list --available --external
python -m esaa --root . plugin install security
```

Install records the plugin in `.roadmap/plugins.lock.json`. It does not make
tasks eligible. Activate a roadmap execution after install:

```powershell
python -m esaa --root . roadmap activate security --execution-id default
python -m esaa --root . roadmap status --detail
python -m esaa --root . eligible
```

If no input is provided, ESAA copies the plugin input example into
`.roadmap/plugin-inputs/` and validates it against the plugin input schema.
