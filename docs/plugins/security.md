# ESAA Plugin Security

Plugin packages are declarative. A plugin may declare `plugin.json`,
`roadmap.template.json`, input examples, input schemas, documentation, fixtures
and auxiliary files. The Orchestrator remains the authority that validates,
persists and applies effects.

The validator rejects unsafe paths in `plugin.json`, `roadmap.template.json`
and local input references. A plugin must not use path traversal, absolute
paths, or governed ESAA state files such as `.roadmap/activity.jsonl`,
`.roadmap/roadmap.json`, `.roadmap/issues.json` or `.roadmap/lessons.json`.

Valid output examples:

```json
{
  "outputs": {
    "files": ["docs/security/baseline.md"]
  }
}
```

Invalid output examples:

```json
{
  "outputs": {
    "files": ["../src/app.py", ".roadmap/activity.jsonl"]
  }
}
```

Run diagnostics before installing a plugin:

```powershell
python -m esaa --root . plugin doctor ./plugins/security
```

