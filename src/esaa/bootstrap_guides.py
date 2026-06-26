from __future__ import annotations

from pathlib import Path

from .errors import ESAAError

GUIDE_MARKER_CONTRACT_BEGIN = "<!-- esaa:bootstrap:contract:begin -->"
GUIDE_MARKER_CONTRACT_END = "<!-- esaa:bootstrap:contract:end -->"
GUIDE_MARKER_PROJECT_BEGIN = "<!-- esaa:bootstrap:project:begin -->"
GUIDE_MARKER_PROJECT_END = "<!-- esaa:bootstrap:project:end -->"

PROJECT_PLACEHOLDER = "## Contexto do projeto\n\n_Adicione aqui regras específicas do seu projeto._\n"
README_CONTRACT = (
    "# ESAA\n\n"
    "Este projeto usa ESAA para governança de agentes: agentes emitem intenções, "
    "o Orchestrator valida e aplica efeitos, e `.roadmap/activity.jsonl` é a fonte da verdade.\n\n"
    "Guias: `docs/guides/`.\n"
)


def should_skip_guide(path: Path, preserve_guides: bool) -> bool:
    return preserve_guides and path.exists()


def _marker_count(text: str, marker: str) -> int:
    return text.count(marker)


def validate_markers(text: str) -> None:
    counts = {
        GUIDE_MARKER_CONTRACT_BEGIN: _marker_count(text, GUIDE_MARKER_CONTRACT_BEGIN),
        GUIDE_MARKER_CONTRACT_END: _marker_count(text, GUIDE_MARKER_CONTRACT_END),
        GUIDE_MARKER_PROJECT_BEGIN: _marker_count(text, GUIDE_MARKER_PROJECT_BEGIN),
        GUIDE_MARKER_PROJECT_END: _marker_count(text, GUIDE_MARKER_PROJECT_END),
    }
    present = {marker: count for marker, count in counts.items() if count}
    if not present:
        return
    if any(count > 1 for count in counts.values()):
        raise ESAAError("BOOTSTRAP_MERGE_AMBIGUOUS", "duplicate bootstrap guide markers")
    if any(count != 1 for count in counts.values()):
        raise ESAAError("BOOTSTRAP_MERGE_INVALID", "incomplete bootstrap guide marker regions")

    contract_begin = text.index(GUIDE_MARKER_CONTRACT_BEGIN)
    contract_end = text.index(GUIDE_MARKER_CONTRACT_END)
    project_begin = text.index(GUIDE_MARKER_PROJECT_BEGIN)
    project_end = text.index(GUIDE_MARKER_PROJECT_END)
    if not (contract_begin < contract_end < project_begin < project_end):
        raise ESAAError("BOOTSTRAP_MERGE_INVALID", "malformed bootstrap guide marker order")


def extract_regions(text: str) -> tuple[str, str]:
    validate_markers(text)
    if GUIDE_MARKER_CONTRACT_BEGIN not in text:
        raise ESAAError("BOOTSTRAP_MERGE_INVALID", "bootstrap guide regions are absent")

    contract_start = text.index(GUIDE_MARKER_CONTRACT_BEGIN) + len(GUIDE_MARKER_CONTRACT_BEGIN)
    contract_end = text.index(GUIDE_MARKER_CONTRACT_END)
    project_start = text.index(GUIDE_MARKER_PROJECT_BEGIN) + len(GUIDE_MARKER_PROJECT_BEGIN)
    project_end = text.index(GUIDE_MARKER_PROJECT_END)
    return text[contract_start:contract_end], text[project_start:project_end]


def _normalize_contract(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _compose_regions(contract: str, project: str) -> str:
    return (
        f"{GUIDE_MARKER_CONTRACT_BEGIN}\n"
        f"{_normalize_contract(contract)}"
        f"{GUIDE_MARKER_CONTRACT_END}\n\n"
        f"{GUIDE_MARKER_PROJECT_BEGIN}"
        f"{project}"
        f"{GUIDE_MARKER_PROJECT_END}\n"
    )


def merge_guide_content(
    existing: str | None,
    contract_template: str,
    *,
    readme_mode: bool = False,
) -> str:
    contract = README_CONTRACT if readme_mode else contract_template
    if existing is None:
        project = "\n" + PROJECT_PLACEHOLDER
    else:
        validate_markers(existing)
        if GUIDE_MARKER_CONTRACT_BEGIN in existing:
            _old_contract, project_region = extract_regions(existing)
            project = project_region
        else:
            project = "\n" + existing

    if not project.endswith("\n"):
        project += "\n"
    return _compose_regions(contract, project)
