# ESAA Plugin Authoring

An ESAA plugin is a directory package. It is not an archive file and it does
not need a custom extension. The root of the directory must contain
`plugin.json`.

Minimum layout:

```text
security/
  plugin.json
  roadmap.template.json
  inputs/
    security.local.example.json
  schemas/
    security-input.schema.json
  README.md
```

`plugin.json` declares the package identity and entrypoints:

```json
{
  "schema_version": "esaa-plugin/v1",
  "id": "security",
  "name": "Security",
  "version": "1.0.0",
  "kind": "roadmap_plugin",
  "esaa_core": {
    "min_version": "0.5.0",
    "max_version": "<0.6.0"
  },
  "entrypoints": {
    "roadmap": "roadmap.template.json",
    "input_example": "inputs/security.local.example.json",
    "input_schema": "schemas/security-input.schema.json"
  },
  "task_id_namespace": "security",
  "capabilities": ["planned_tasks", "local_input"]
}
```

The `roadmap.template.json` file contains planned tasks. Local task ids may be
simple, such as `T-001`; ESAA namespaces them at activation time, for example
`security-default-T-001`.

Create a starter plugin:

```powershell
python -m esaa --root . plugin new security
python -m esaa --root . plugin validate ./security
python -m esaa --root . plugin doctor ./security
```

