# Plugin Example

Create and use a local plugin folder:

```powershell
esaa plugin new security
esaa plugin validate ./security
esaa plugin doctor ./security
esaa plugin install ./security
esaa roadmap activate security --execution-id default
esaa eligible
```

An ESAA plugin is a directory package with `plugin.json` and
`roadmap.template.json` at its root.

