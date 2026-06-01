# Repository Hygiene

Operational cleanup must preserve canonical ESAA state.

- Never ignore `.roadmap/activity.jsonl`; it is the append-only source of truth.
- Never ignore `.roadmap/roadmap.json`, `.roadmap/issues.json`, or `.roadmap/lessons.json`; they are read models and must stay auditable.
- Do ignore transient caches such as `__pycache__/`, `.pytest_cache/`, `*.pyc`, locks, backups, and staging leftovers.
- Rebuild generated distributions after source changes instead of keeping stale `dist/` artifacts.
