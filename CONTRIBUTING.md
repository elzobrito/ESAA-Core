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

## Documentation: bilingual guides

The user-facing guides under `docs/guides/` and `docs/security/threat-model.md`
ship in two languages:

- **Portuguese is the canonical source** — the no-suffix file (e.g.
  `esaa-cenarios.md`).
- **English lives in a `.en.md` sibling** (e.g. `esaa-cenarios.en.md`).

Each file carries a language switcher line right under the title, and the
`README.md` Usage Guides links point to the `.en.md` versions.

To avoid drift, **any content change to a guide must update its `.en.md` sibling
in the same pull request** (and vice versa). When changing a translated guide,
also check:

- intra-guide links in the EN version point to `.en.md` siblings; links to
  `../plugins/*.md` stay as-is (those docs are already English);
- in-page anchors still resolve — translated headings change the GitHub slug, so
  update the index/cross-references (this matters most for `esaa-cenarios.en.md`);
- code blocks stay identical except for localized comments and example
  placeholders (commands, JSON, YAML, flags, and reject codes must not change).

