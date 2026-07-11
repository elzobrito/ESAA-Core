from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .conflicts import conflict_between_sets, normalize_write_set
from .dispatch import build_minimal_context
from .plugins import load_active_roadmap_tasks

BASELINE_LESSONS: list[dict[str, Any]] = [
    {
        "lesson_id": "LES-0001",
        "status": "active",
        "title": "Nunca colapsar claim + complete",
        "mistake": "Agente emitiu complete sem claim previo; tarefa nao transita corretamente.",
        "rule": "Cada invocacao emite exatamente uma action. claim e complete sao outputs separados.",
        "scope": {"task_kinds": ["spec", "impl", "qa"]},
        "enforcement": {"mode": "reject", "applies_to": "workflow_gate"},
        "source_refs": [{"type": "gate", "ref": "WG-001"}, {"type": "gate", "ref": "WG-005"}],
    },
    {
        "lesson_id": "LES-0002",
        "status": "active",
        "title": "file_updates exige action=complete",
        "mistake": "file_updates emitido com claim/review/issue.report; nao deveria existir.",
        "rule": "Todo file_updates DEVE acompanhar action=complete; outros actions sao rejeitados.",
        "scope": {"task_kinds": ["spec", "impl", "qa"]},
        "enforcement": {"mode": "reject", "applies_to": "output_contract"},
        "source_refs": [{"type": "gate", "ref": "WG-002"}],
    },
    {
        "lesson_id": "LES-0003",
        "status": "active",
        "title": "prior_status obrigatorio e coerente",
        "mistake": "prior_status omitido ou divergente do status real do roadmap.",
        "rule": "prior_status e obrigatorio em todo output e deve refletir o status do roadmap.",
        "scope": {"task_kinds": ["spec", "impl", "qa"]},
        "enforcement": {"mode": "require_field", "applies_to": "output_contract"},
        "source_refs": [{"type": "gate", "ref": "WG-003"}],
    },
]


def seed_tasks() -> list[dict[str, Any]]:
    """Demo baseline tasks for `init --with-demo-tasks` (not used by default init)."""


    return [
        {
            "task_id": "T-1000",
            "task_kind": "spec",
            "title": "Create initial ESAA spec document",
            "description": "Produce the initial specification artifact for the ESAA core baseline.",
            "depends_on": [],
            "targets": ["spec-core"],
            "outputs": {"files": ["docs/spec/T-1000.md"]},
        },
        {
            "task_id": "T-1010",
            "task_kind": "impl",
            "title": "Create initial implementation artifact",
            "description": "Produce the initial implementation artifact that follows the approved specification.",
            "depends_on": ["T-1000"],
            "targets": ["impl-core"],
            "outputs": {"files": ["src/T-1010.txt"]},
        },
        {
            "task_id": "T-1020",
            "task_kind": "qa",
            "title": "Create initial QA report",
            "description": "Produce the initial QA evidence artifact validating the implementation baseline.",
            "depends_on": ["T-1010"],
            "targets": ["qa-core"],
            "outputs": {"files": ["docs/qa/T-1020.md"]},
        },
    ]


def _enrich_audit_description(task: dict[str, Any]) -> str:

    base = task.get("description") or task.get("title", "")

    pointer_parts: list[str] = []

    playbook_ref = task.get("playbook_ref")

    if playbook_ref:

        pointer_parts.append(f"Playbook: {playbook_ref}")

    checks = task.get("checks_covered")

    if checks:

        pointer_parts.append("Checks: " + ", ".join(checks))

    owasp = task.get("owasp_mapping")

    if owasp:

        pointer_parts.append("OWASP/CWE: " + ", ".join(owasp))

    if not pointer_parts:

        return base

    ref = playbook_ref or task["task_id"]

    suffix = " | ".join(pointer_parts)

    return f"{base} | {suffix} | Detalhes executaveis em .roadmap/playbooks.security.json[{ref}]."


def load_plugin_seeds(root: Path) -> dict[str, Any] | None:
    """R9 - Loader generico de plugins instalados e compat roadmap.*.json.



    Primeiro carrega roadmaps ativos declarados em `.roadmap/roadmaps.lock.json`.
    Em seguida, por compatibilidade temporaria, descobre arquivos
    `.roadmap/roadmap.*.json` (exceto `roadmap.json`, `roadmap.schema.json` e
    `*.template.json`),

    valida superficialmente, projeta cada tarefa para o subset do schema 0.4.x

    e deduplica por task_id (primeira ocorrencia vence).

    """

    installed_seed = load_active_roadmap_tasks(root)

    plugins = sorted((root / ".roadmap").glob("roadmap.*.json"))

    plugins = [
        p
        for p in plugins
        if p.name not in {"roadmap.json", "roadmap.schema.json"} and not p.name.endswith(".template.json")
    ]

    if not plugins and not installed_seed:

        return None

    project_name: str | None = None

    audit_scope: str | None = None

    seen: set[str] = set()

    tasks: list[dict[str, Any]] = []

    if installed_seed:

        project_name = installed_seed.get("project_name")

        audit_scope = installed_seed.get("audit_scope")

        for task in installed_seed.get("tasks", []):

            tid = task.get("task_id")

            if not tid or tid in seen:

                continue

            seen.add(tid)

            tasks.append(dict(task))

    for plugin in plugins:

        raw = json.loads(plugin.read_text(encoding="utf-8"))

        project = raw.get("project", {}) or {}

        if project_name is None:

            project_name = project.get("name")

        if audit_scope is None:

            audit_scope = project.get("audit_scope")

        for task in raw.get("tasks", []):

            tid = task.get("task_id")

            if not tid or tid in seen:

                continue

            seen.add(tid)

            tasks.append(
                {
                    "task_id": tid,
                    "task_kind": task["task_kind"],
                    "title": task["title"],
                    "description": _enrich_audit_description(task),
                    "depends_on": list(task.get("depends_on", [])),
                    "targets": list(task.get("targets", [])),
                    "outputs": task.get("outputs", {"files": []}),
                }
            )

    if not tasks:

        return None

    return {"project_name": project_name, "audit_scope": audit_scope, "tasks": tasks}


def find_planned_plugin_task(root: Path, task_id: str) -> dict[str, Any] | None:

    seed = load_plugin_seeds(root)

    if not seed:

        return None

    for task in seed["tasks"]:

        if task["task_id"] == task_id:

            return dict(task)

    return None


def tasks_with_planned_plugins(
    root: Path, event_tasks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Une tarefas materializadas com tarefas planejadas em roadmap plugins.



    O event store continua sendo a prova do que aconteceu. Tarefas presentes

    apenas em `roadmap.*.json` entram como planejadas para selecao/elegibilidade,

    sem gerar `task.create` ou mutar read models.

    """

    sources = {task["task_id"]: "event_store" for task in event_tasks}

    tasks = list(event_tasks)

    seed = load_plugin_seeds(root)

    if not seed:

        return tasks, sources

    seen = set(sources)

    for task in seed["tasks"]:

        task_id = task["task_id"]

        if task_id in seen:

            continue

        planned = dict(task)

        planned["status"] = "todo"

        planned["immutability"] = {"done_is_immutable": True}

        tasks.append(planned)

        sources[task_id] = "roadmap_plugin"

        seen.add(task_id)

    return tasks, sources


# Backcompat - antigos chamadores podem usar load_audit_seed.


def load_audit_seed(root: Path) -> dict[str, Any] | None:

    return load_plugin_seeds(root)


def all_tasks_done(tasks: list[dict[str, Any]]) -> bool:

    active_tasks = [task for task in tasks if not task.get("superseded_by")]
    return bool(active_tasks) and all(task["status"] == "done" for task in active_tasks)


def select_next_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:

    by_id = {task["task_id"]: task for task in tasks}
    active_tasks = [task for task in tasks if not task.get("superseded_by")]

    for status in ("review", "in_progress"):

        candidates = sorted(
            [task for task in active_tasks if task["status"] == status], key=lambda item: item["task_id"]
        )

        if candidates:

            return candidates[0]

    todo = sorted([task for task in active_tasks if task["status"] == "todo"], key=lambda item: item["task_id"])

    for task in todo:

        deps = task.get("depends_on", [])

        if all(by_id[dep]["status"] == "done" for dep in deps if dep in by_id):

            return task

    return None


def select_task_wave(tasks: list[dict[str, Any]], limit: int = 1) -> list[dict[str, Any]]:

    if limit <= 1:

        task = select_next_task(tasks)

        return [task] if task else []

    by_id = {task["task_id"]: task for task in tasks}
    active_tasks = [task for task in tasks if not task.get("superseded_by")]

    for status in ("review", "in_progress"):

        candidates = sorted(
            [task for task in active_tasks if task["status"] == status], key=lambda item: item["task_id"]
        )

        if candidates:

            return candidates[:limit]

    eligible = list_eligible_tasks(tasks)

    groups = parallel_groups(eligible)

    if not groups:

        return []

    return [by_id[task_id] for task_id in groups[0][:limit] if task_id in by_id]


def list_eligible_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:

    by_id = {t["task_id"]: t for t in tasks}

    out: list[dict[str, Any]] = []

    for task in sorted(tasks, key=lambda t: t["task_id"]):

        if task.get("superseded_by"):

            continue

        if task["status"] != "todo":

            continue

        deps = task.get("depends_on", [])

        if all(by_id.get(d, {}).get("status") == "done" for d in deps):

            out.append(task)

    return out


def parallel_groups(eligible: list[dict[str, Any]]) -> list[list[str]]:

    groups: list[dict[str, Any]] = []

    for task in eligible:

        files = normalize_write_set(task.get("outputs", {}).get("files", []))

        placed = False

        for g in groups:

            if not conflict_between_sets(g["files"], files):

                g["files"].extend(files)

                g["tasks"].append(task["task_id"])

                placed = True

                break

        if not placed:

            groups.append({"files": list(files), "tasks": [task["task_id"]]})

    return [g["tasks"] for g in groups]


def build_dispatch_context(
    roadmap: dict[str, Any],
    task: dict[str, Any],
    contract: dict[str, Any],
    schema: dict[str, Any] | None = None,
    lessons: list[dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
    project_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:

    if schema is not None:

        return build_minimal_context(
            roadmap,
            task,
            contract,
            schema,
            lessons,
            issues,
            project_profile=project_profile,
        )

    boundaries = contract["boundaries"]["by_task_kind"][task["task_kind"]]

    ctx = {
        "boundaries": {"read": boundaries.get("read", []), "write": boundaries.get("write", [])},
        "context_pack": {"run": roadmap["meta"]["run"], "project": roadmap["project"]},
        "task": task,
        "correlation": {
            "master_correlation_id": roadmap["meta"].get("master_correlation_id"),
            "task_id": task["task_id"],
        },
    }
    if project_profile is not None:
        ctx["project_profile"] = project_profile
    return ctx
