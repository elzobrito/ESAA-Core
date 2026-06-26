from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from .bootstrap_guides import merge_guide_content, should_skip_guide, validate_markers
from .errors import ESAAError

GOVERNANCE_TEMPLATE_FILES = (
    "AGENT_CONTRACT.yaml",
    "ORCHESTRATOR_CONTRACT.yaml",
    "RUNTIME_POLICY.yaml",
    "STORAGE_POLICY.yaml",
    "PROJECTION_SPEC.md",
    "agent_result.schema.json",
    "roadmap.schema.json",
    "issues.schema.json",
    "lessons.schema.json",
    "agents_swarm.yaml",
    "PARCER_PROFILE.agent-docs.yaml",
    "PARCER_PROFILE.agent-spec.yaml",
    "PARCER_PROFILE.agent-impl.yaml",
    "PARCER_PROFILE.agent-qa.yaml",
    "PARCER_PROFILE.orchestrator-runtime.yaml",
)

AGENT_GUIDE_TEMPLATE_FILES = (
    ("README.md", "README.md"),
    ("AGENTS.md", "AGENTS.md"),
    ("CLAUDE.md", ".claude/CLAUDE.md"),
)

PROFILES = {"public", "production"}

PROTECTED_RELATIVE_PATHS = {
    ".roadmap/activity.jsonl",
    ".roadmap/roadmap.json",
    ".roadmap/issues.json",
    ".roadmap/lessons.json",
    ".roadmap/artifacts",
    ".roadmap/backups",
    ".roadmap/snapshots",
}


def _template_bytes(name: str) -> bytes:
    template = resources.files("esaa").joinpath("templates", name)
    return template.read_bytes()


def _workspace_template_bytes(name: str) -> bytes:
    template = resources.files("esaa").joinpath("workspace", name)
    return template.read_bytes()


def bootstrap_workspace(
    root: Path,
    profile: str = "public",
    force: bool = False,
    *,
    preserve_guides: bool = False,
    merge_guides: bool = False,
) -> dict[str, Any]:
    """Copy packaged ESAA governance templates into a workspace.

    Bootstrap installs the public governance bundle: contracts, schemas,
    runtime/storage policy, projection spec, PARCER profiles, README, and
    minimal agent guidance files. Event stores and materialized read models
    stay untouched so a public package can safely prepare existing workspaces.
    """
    if profile not in PROFILES:
        raise ESAAError("BOOTSTRAP_PROFILE_INVALID", f"profile must be one of {sorted(PROFILES)}")
    if preserve_guides and merge_guides:
        raise ESAAError("BOOTSTRAP_FLAGS_CONFLICT", "--preserve-guides and --merge-guides are mutually exclusive")

    root = Path(root)
    roadmap_dir = root / ".roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)

    governance_targets = [
        (f".roadmap/{name}", roadmap_dir / name, "governance", name) for name in GOVERNANCE_TEMPLATE_FILES
    ]
    guide_targets = [
        (target_rel, root / target_rel, "workspace", source_name)
        for source_name, target_rel in AGENT_GUIDE_TEMPLATE_FILES
    ]
    existing_targets = governance_targets if preserve_guides or merge_guides else [*governance_targets, *guide_targets]
    existing = [rel for rel, path, _kind, _source in existing_targets if path.exists()]
    if existing and not force:
        raise ESAAError(
            "BOOTSTRAP_TARGET_EXISTS",
            "governance files already exist; use --force to overwrite allowlisted files",
        )
    if merge_guides:
        for _rel, path, _kind, _source in guide_targets:
            if path.exists():
                validate_markers(path.read_text(encoding="utf-8"))

    files_written: list[str] = []
    files_preserved: list[str] = []
    files_merged: list[str] = []
    notes: dict[str, Any] = {}

    for rel, path, _kind, source in governance_targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_template_bytes(source))
        files_written.append(rel)

    for rel, path, _kind, source in guide_targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        if should_skip_guide(path, preserve_guides):
            files_preserved.append(rel)
            continue
        if merge_guides:
            existing_text = path.read_text(encoding="utf-8") if path.exists() else None
            merged = merge_guide_content(
                existing_text,
                _workspace_template_bytes(source).decode("utf-8"),
                readme_mode=source == "README.md",
            )
            path.write_text(merged, encoding="utf-8", newline="")
            files_written.append(rel)
            files_merged.append(rel)
        else:
            path.write_bytes(_workspace_template_bytes(source))
            files_written.append(rel)

    if merge_guides and (root / "CLAUDE.md").exists():
        notes["root_claude_ignored"] = True

    if preserve_guides:
        guide_mode = "preserve"
    elif merge_guides:
        guide_mode = "merge"
    elif force:
        guide_mode = "overwrite"
    else:
        guide_mode = "default"

    result: dict[str, Any] = {
        "status": "bootstrapped",
        "profile": profile,
        "force": force,
        "guide_mode": guide_mode,
        "files_written": files_written,
        "protected_paths": sorted(PROTECTED_RELATIVE_PATHS),
    }
    if files_preserved:
        result["files_preserved"] = files_preserved
    if files_merged:
        result["files_merged"] = files_merged
    if notes:
        result["notes"] = notes

    return result
