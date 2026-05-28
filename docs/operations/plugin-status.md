# `esaa plugin-status` — Plugin × Projection Cross-View

> CLI helper that answers: "of the tasks declared by plugin X, how many are
> done / in flight / still planned?" Without it, the operator must manually
> cross-reference each `task_id` between the plugin catalog
> (`.roadmap/roadmap*.json`) and the live projection (`.roadmap/roadmap.json`).

## Why this command exists

Roadmap plugins in ESAA are **immutable catalogs** of planned work. Live state
lives in the event store (`.roadmap/activity.jsonl`) and is exposed through
the projection (`.roadmap/roadmap.json`). The two files are intentionally
decoupled:

- A plugin file with all tasks `status: todo` may have 90% of its work
  already `done` — the projection holds that fact.
- Plugin entries without lifecycle events are *planned work*, not a mismatch.

This makes it impossible to answer "how much progress did plugin X make?"
just by opening files. Existing CLI surfaces (`eligible`, `state`, `metrics`)
either show only executable tasks or require a per-task lookup.

`plugin-status` aggregates the cross-reference deterministically and reports
per-plugin counts plus an optional task-level breakdown.

## Usage

```bash
# Summary across all plugins
esaa --root . plugin-status

# Filter to a single plugin
esaa --root . plugin-status --plugin roadmap.sso-client.json

# Include per-task list (task_id, kind, planned status, live status)
esaa --root . plugin-status --detail

# Combine
esaa --root . plugin-status --plugin roadmap.sso-client.json --detail
```

## Output schema

```json
{
  "root": "<absolute path>",
  "projection_present": true,
  "plugins": [
    {
      "plugin_file": ".roadmap/roadmap.sso-client.json",
      "tasks_declared": 36,
      "in_projection": 3,
      "by_live_status":    { "done": 3, "todo": 33 },
      "by_planned_status": { "todo": 36 },
      "tasks": [                              // only when --detail
        {
          "task_id": "T-001",
          "title": "[SPEC] G0 — Stack + runtime contract discovery",
          "kind": "spec",
          "planned_status": "todo",
          "live_status": "done"
        }
      ]
    }
  ],
  "grand_totals_by_live_status": { "done": 44, "review": 2, "todo": 134 }
}
```

### Field semantics

| Field | Meaning |
| --- | --- |
| `plugin_file` | Path relative to `--root` of the plugin file (or `roadmap.json` itself, which is included so the totals are complete). |
| `tasks_declared` | `len(plugin.tasks)` — what the catalog promises. |
| `in_projection` | Number of those `task_id`s that have at least one event in the store (i.e., appear in the projection). |
| `by_live_status` | Histogram using the **live** status when known, **planned** status as fallback. This is the column you read to know "what really is in this plugin right now". |
| `by_planned_status` | Histogram of what the plugin *file* itself declares. Diverging from `by_live_status` is normal; **a plugin whose own `tasks[].status` includes `done` without matching events is suspicious** — it means someone hand-edited the catalog (which violates "Do not edit read models by hand"). |
| `tasks[].live_status` | `null` when the task has never been admitted (no `task.create` event). The `tasks[].title` and `tasks[].kind` come straight from the plugin. |
| `grand_totals_by_live_status` | Aggregate across all listed plugins. Includes `roadmap.json` itself when present, so the sum is the universe of known work. |

## Exit semantics

- Exit `0` on success. The command is a read-only inspection and never
  consumes attempts or mutates state.
- Exit `1` on `ROADMAP_DIR_MISSING` (no `.roadmap/` under `--root`).
- Exit `1` on `PROJECTION_UNREADABLE` when `roadmap.json` exists but cannot
  be parsed as JSON.

The command does **not** require `verify_status == ok`. It is safe to run
during partial state, mid-migration, or right after `bootstrap` before any
event has been admitted.

## Use cases

1. **Operator daily check.** `esaa plugin-status` once per session to see
   which plugins moved.
2. **Plugin handoff.** Before publishing a new plugin, confirm
   `by_planned_status` is exclusively `todo` — otherwise the catalog is
   carrying stale `done` markers.
3. **Hand-edit detection.** If `by_planned_status` shows `done` for any
   plugin other than `roadmap.json`, that file was edited outside the event
   loop. Investigate before reprojecting (otherwise the projection will
   continue to show the truth from the event store; the plugin remains
   misleading until corrected).
4. **Stalled-work radar.** A plugin with `tasks_declared > in_projection`
   for an extended period has untouched planned work.

## Implementation notes

Single helper in `src/esaa/cli.py` (no new module). Reads `.roadmap/` only;
never writes. No dependency on `service.py`, no event emission.

### Files touched

| File | Change |
| --- | --- |
| `src/esaa/cli.py` | new helper `_plugin_status(...)`, new parser block, new dispatch arm |

### Patch overview (annotated)

**1. Parser block — insert after the `metrics` parser** (around the existing
line that reads `sub.add_parser("metrics", ...)`):

```python
cmd_plugin_status = sub.add_parser(
    "plugin-status",
    help="show planned-vs-projected status per roadmap plugin",
)
cmd_plugin_status.add_argument(
    "--detail", action="store_true",
    help="include per-task list (task_id, title, projected status)",
)
cmd_plugin_status.add_argument(
    "--plugin", default=None,
    help="filter to one plugin filename (e.g. roadmap.sso-client.json)",
)
```

**2. Dispatch arm — insert right after the `metrics` handler:**

```python
elif args.command == "plugin-status":
    result = _plugin_status(root, detail=args.detail, plugin_filter=args.plugin)
```

**3. Helper function — module-level, anywhere before `_build_parser`:**

```python
def _plugin_status(root: Path, detail: bool = False, plugin_filter: str | None = None) -> dict:
    """Cross-reference planned tasks (per-plugin) with projected state."""
    roadmap_dir = root / ".roadmap"
    if not roadmap_dir.is_dir():
        raise ESAAError("ROADMAP_DIR_MISSING", f".roadmap not found under {root}")

    projection_path = roadmap_dir / "roadmap.json"
    projected_status: dict[str, str] = {}
    if projection_path.is_file():
        try:
            proj = json.loads(projection_path.read_text(encoding="utf-8"))
            for t in proj.get("tasks", []):
                tid = t.get("task_id")
                if tid:
                    projected_status[tid] = t.get("status", "?")
        except (ValueError, OSError) as exc:
            raise ESAAError("PROJECTION_UNREADABLE", str(exc)) from exc

    plugins: list[dict] = []
    grand_totals: dict[str, int] = {}

    for path in sorted(roadmap_dir.glob("roadmap*.json")):
        if path.name == "roadmap.schema.json":
            continue
        if plugin_filter and path.name != plugin_filter:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        tasks = data.get("tasks") or []
        if not tasks:
            continue

        by_planned_status: dict[str, int] = {}
        by_live_status: dict[str, int] = {}
        in_projection = 0
        items: list[dict] = []

        for t in tasks:
            tid = t.get("task_id", "?")
            planned = t.get("status", "todo")
            live = projected_status.get(tid)
            by_planned_status[planned] = by_planned_status.get(planned, 0) + 1
            effective = live if live is not None else planned
            by_live_status[effective] = by_live_status.get(effective, 0) + 1
            grand_totals[effective] = grand_totals.get(effective, 0) + 1
            if live is not None:
                in_projection += 1
            if detail:
                items.append({
                    "task_id": tid,
                    "title": t.get("title", ""),
                    "kind": t.get("task_kind"),
                    "planned_status": planned,
                    "live_status": live,
                })

        plugins.append({
            "plugin_file": str(path.relative_to(root)).replace("\\", "/"),
            "tasks_declared": len(tasks),
            "in_projection": in_projection,
            "by_live_status": by_live_status,
            "by_planned_status": by_planned_status,
            **({"tasks": items} if detail else {}),
        })

    return {
        "root": str(root),
        "projection_present": projection_path.is_file(),
        "plugins": plugins,
        "grand_totals_by_live_status": grand_totals,
    }
```

The helper uses only stdlib (`json`, `pathlib`) and the project's own
`ESAAError`. No imports need to be added — the relevant ones (`json`, `Path`,
`ESAAError`) are already at the top of `cli.py`.

## Tests (recommended)

Stash a small fixture under `tests/cli/plugin_status_fixture/.roadmap/` with:

- `roadmap.json` (projection): 2 tasks, one `done`, one `review`.
- `roadmap.example.json` (plugin): 4 tasks, all `todo`, two of which share
  `task_id` with the projection.

Then assert:

- `by_live_status == {"done": 1, "review": 1, "todo": 2}` for the plugin.
- `by_planned_status == {"todo": 4}` for the plugin.
- `in_projection == 2`.
- `--plugin roadmap.example.json` filters to a single entry.
- `--detail` emits 4 task entries, two with `live_status is not None`.
- Missing `.roadmap/` raises `ROADMAP_DIR_MISSING`.

## Caveats and non-goals

- **Read-only.** This command is *not* a substitute for `verify`; it does
  not check hash consistency.
- **Status terms come from the plugin and projection as-is.** Custom status
  strings (e.g., from a non-core profile) are passed through unchanged.
- **Hand-edit detection is heuristic.** A `done` in `by_planned_status` for
  a non-`roadmap.json` plugin is a strong signal of past hand-editing, but
  some legitimate workflows (snapshot reseed, bulk import) might also
  produce it. Investigate before drawing conclusions.
- **No JSON-Schema for the output yet.** The shape above is stable for v1;
  add a `plugin-status.schema.json` if downstream automation depends on it.

## Changelog entry suggestion

```
- Added: `esaa plugin-status` CLI command. Cross-references each
  .roadmap/roadmap*.json plugin against the live projection and reports
  per-plugin task counts plus optional task-level detail. Read-only.
```
