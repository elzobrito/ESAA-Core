from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .constants import SCHEMA_VERSION
from .errors import ESAAError
from .utils import utc_now_iso

GUIDE_PATHS = (
    ("AGENTS.md", "agent-guide"),
    ("CLAUDE.md", "root-claude-guide"),
    (".claude/CLAUDE.md", "claude-guide"),
    ("README.md", "readme"),
    ("readme.md", "readme"),
)

SOURCE_CANDIDATES = ("AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", "README.md", "readme.md", "docs/spec")
OUTPUT_CANDIDATES = ("src", "app", "docs", "tests")
PROTECTED_DEFAULTS = (".roadmap/**", ".env", ".env.*", "*secret*", "*secrets*")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ESAAError("PROJECT_PROFILE_INVALID", "expected string or array of strings")


def detect_guide_topology(root: Path) -> dict[str, Any]:
    return {
        "guides": [
            {"path": path, "exists": (root / path).exists(), "role": role}
            for path, role in GUIDE_PATHS
        ]
    }


def _existing_paths(root: Path, candidates: tuple[str, ...], suffix: str = "") -> list[str]:
    paths: list[str] = []
    for candidate in candidates:
        if (root / candidate).exists():
            paths.append(f"{candidate}{suffix}")
    return paths


def _operator(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("operator") or {}
    if raw is not None and not isinstance(raw, dict):
        raise ESAAError("PROJECT_PROFILE_INVALID", "operator must be an object")
    display_name = str(
        payload.get("operator_name")
        or payload.get("display_name")
        or payload.get("user_name")
        or raw.get("display_name", "")
    ).strip()
    return {"display_name": display_name}


def normalize_project_profile(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ESAAError("PROJECT_PROFILE_INVALID", "project profile answers must be an object")
    project_name = str(payload.get("project_name") or payload.get("name") or root.name).strip()
    domain = str(payload.get("domain") or "general-software").strip()
    language = str(payload.get("language") or payload.get("locale") or "pt-BR").strip()
    if not project_name:
        raise ESAAError("PROJECT_PROFILE_INVALID", "project_name is required")
    if not domain:
        raise ESAAError("PROJECT_PROFILE_INVALID", "domain is required")
    if not language:
        raise ESAAError("PROJECT_PROFILE_INVALID", "language is required")
    workflow = payload.get("workflow_preferences") or {}
    if not isinstance(workflow, dict):
        raise ESAAError("PROJECT_PROFILE_INVALID", "workflow_preferences must be an object")
    return {
        "operator": _operator(payload),
        "project_name": project_name,
        "domain": domain,
        "language": language,
        "sources_of_truth": _string_list(payload.get("sources_of_truth"))
        or _existing_paths(root, SOURCE_CANDIDATES),
        "output_surfaces": _string_list(payload.get("output_surfaces"))
        or _existing_paths(root, OUTPUT_CANDIDATES, "/**"),
        "protected_paths": _string_list(payload.get("protected_paths"))
        or list(PROTECTED_DEFAULTS),
        "workflow_preferences": dict(workflow),
        "guide_topology": payload.get("guide_topology") or detect_guide_topology(root),
    }


def project_profile_view(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    profile: dict[str, Any] | None = None
    last_event_seq = 0
    updated_at = utc_now_iso()
    for event in events:
        if event.get("action") != "project.profile.set":
            continue
        payload = event.get("payload") or {}
        profile = {
            "operator": dict(payload.get("operator", {"display_name": ""})),
            "project_name": payload["project_name"],
            "domain": payload["domain"],
            "language": payload["language"],
            "sources_of_truth": list(payload.get("sources_of_truth", [])),
            "output_surfaces": list(payload.get("output_surfaces", [])),
            "protected_paths": list(payload.get("protected_paths", [])),
            "workflow_preferences": dict(payload.get("workflow_preferences", {})),
            "guide_topology": dict(payload.get("guide_topology", {"guides": []})),
        }
        last_event_seq = int(event["event_seq"])
        updated_at = event["ts"]
    if profile is None:
        return None
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_by": "esaa.project_profile",
            "source_event_store": ".roadmap/activity.jsonl",
            "last_event_seq": last_event_seq,
            "updated_at": updated_at,
        },
        **profile,
    }


def project_profile_summary(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "operator": profile.get("operator", {"display_name": ""}),
        "project_name": profile["project_name"],
        "domain": profile["domain"],
        "language": profile["language"],
        "sources_of_truth": profile.get("sources_of_truth", []),
        "output_surfaces": profile.get("output_surfaces", []),
        "protected_paths": profile.get("protected_paths", []),
    }


def validate_project_profile(profile: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(profile), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        loc = "/".join(str(part) for part in error.path) or "<root>"
        raise ESAAError("SCHEMA_INVALID", f"project_profile.schema.json {loc}: {error.message}")


def build_onboarding_tasks(profile: dict[str, Any], supersedes_existing: set[str]) -> list[dict[str, Any]]:
    supersedes = {
        "GOV-PROFILE-001": ["T-1000"],
        "GOV-PROFILE-010": ["T-1010"],
        "GOV-PROFILE-020": ["T-1020"],
    }
    tasks = [
        {
            "task_id": "GOV-PROFILE-001",
            "task_kind": "spec",
            "title": f"Especificar contrato operacional de {profile['project_name']}",
            "description": "Extrair fontes de verdade, boundaries e workflow inicial do perfil governado.",
            "depends_on": [],
            "targets": ["project-governance"],
            "outputs": {"files": ["docs/spec/GOV-PROFILE-001.md"]},
            "task_type": "governance",
            "acceptance_criteria": [
                "Contrato identifica fontes de verdade e paths protegidos do projeto.",
                "Contrato define outputs e workflow inicial sem sobrescrever guias existentes.",
            ],
            "required_review_mode": "governance",
        },
        {
            "task_id": "GOV-PROFILE-010",
            "task_kind": "impl",
            "title": f"Materializar contrato operacional de {profile['project_name']}",
            "description": "Criar documento operacional versionado a partir da especificação do perfil.",
            "depends_on": ["GOV-PROFILE-001"],
            "targets": ["project-governance"],
            "outputs": {"files": ["docs/governance/project-operational-contract.md"]},
            "boundary_grant": ["docs/governance/**"],
            "task_type": "governance",
            "acceptance_criteria": [
                "Documento separa fontes, outputs, guias e paths protegidos.",
                "Documento inclui comandos mínimos de verificação do projeto.",
            ],
            "required_review_mode": "governance",
        },
        {
            "task_id": "GOV-PROFILE-020",
            "task_kind": "qa",
            "title": f"Validar onboarding governado de {profile['project_name']}",
            "description": "Validar que o perfil e a trilha inicial refletem o workspace sem mutar guias existentes.",
            "depends_on": ["GOV-PROFILE-010"],
            "targets": ["project-governance"],
            "outputs": {"files": ["docs/qa/project-onboarding.md"]},
            "task_type": "governance",
            "acceptance_criteria": [
                "Relatório confirma verify ok após onboarding.",
                "Relatório confirma que guias existentes foram detectados, não sobrescritos.",
            ],
            "required_review_mode": "governance",
        },
    ]
    for task in tasks:
        existing = [task_id for task_id in supersedes[task["task_id"]] if task_id in supersedes_existing]
        if existing:
            task["supersedes"] = existing
    return tasks
