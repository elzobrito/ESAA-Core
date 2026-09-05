from __future__ import annotations

from pathlib import Path


def test_gitignore_keeps_canonical_esaa_files_tracked(repo_root: Path) -> None:
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".roadmap/activity.jsonl" not in text
    assert ".roadmap/roadmap.json" not in text
    assert ".roadmap/backups/" in text
    assert "*.lock" in text


def test_gitignore_patterns_are_well_formed(repo_root: Path) -> None:
    """QUA-03: o typo ./roadmap (que nao corresponde a .roadmap) nao pode voltar."""
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert "./roadmap" not in text, "padrao com ./ nao corresponde a .roadmap em gitignore"
    assert ".roadmap/artifacts/" in text
    assert "dist/" in text


def test_gitignore_covers_bytecode(repo_root: Path) -> None:
    """QUA-03: bytecode regenera em runtime; o que importa e estar ignorado."""
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in text
    assert "*.py[cod]" in text


def test_no_mojibake_in_source(repo_root: Path) -> None:
    """QUA-01: nenhuma sequencia cp1252-sobre-utf8 (ex.: em dash duplamente codificado).

    "Ãƒ" cobre o A-til duplamente codificado (ex.: "NÃƒO"); "ÃO" nao entra nos
    suspects porque a palavra correta "NÃO" o contem legitimamente.
    """
    suspects = ("â€", "Ã©", "Ã­", "Ãƒ")
    targets = list((repo_root / "src").rglob("*.py"))
    targets += [p for p in (repo_root / "src" / "esaa" / "templates").iterdir() if p.is_file()]
    targets += [repo_root / "AGENTS.md", repo_root / ".claude" / "CLAUDE.md"]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for s in suspects:
            assert s not in text, f"mojibake em {path.name}: {s!r}"


def test_client_assets_moved_out_of_roadmap(repo_root: Path) -> None:
    """QUA-04: .roadmap/ contem apenas governanca do framework."""
    for name in (
        "sso-config.sql",
        "roadmap.sso-client-all-in-one.template.json",
        "SsoAllIn-portugues-estruturado.md",
        "sso-client-input.local.example.json",
    ):
        assert not (repo_root / ".roadmap" / name).exists(), f"{name} ainda em .roadmap/"
        assert (repo_root / "examples/plugins/sso-client" / name).exists(), f"{name} ausente do destino"


def test_audit_scripts_outside_package_tree(repo_root: Path) -> None:
    """QUA-05: scripts one-off vivem em tools/, fora da arvore distribuivel."""
    assert not (repo_root / "src/audit").exists(), "src/audit deveria ter sido movido para tools/audit"
    assert (repo_root / "tools/audit/critical_findings.py").exists()


def test_ci_workflow_exists_with_required_jobs(repo_root: Path) -> None:
    """QUA-06: pipeline com lint + matriz de testes."""
    ci = repo_root / ".github/workflows/ci.yml"
    assert ci.exists()
    text = ci.read_text(encoding="utf-8")
    for needle in ("ruff check", "black --check", "matrix", "3.11", "3.12", "3.13", "pytest"):
        assert needle in text, f"CI sem: {needle}"


def test_repository_hygiene_doc_exists(repo_root: Path) -> None:
    doc = repo_root / "docs/operations/repository-hygiene.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "Never ignore `.roadmap/activity.jsonl`" in text


def test_reference_separates_tracked_layout_from_runtime_created_paths(repo_root: Path) -> None:
    readme = (repo_root / "readme.md").read_text(encoding="utf-8")
    assert "docs/guides/esaa-cli-reference.en.md" in readme
    text = (repo_root / "docs/guides/esaa-cli-reference.en.md").read_text(encoding="utf-8")
    tracked = text.split("### Tracked sources", 1)[1].split("### Paths created by operations", 1)[0]
    generated = text.split("### Paths created by operations", 1)[1].split("### Layout and projections", 1)[0]
    assert ".roadmap/AGENT_CONTRACT.yaml" in tracked
    for path in (".roadmap/plugins.lock.json", ".roadmap/roadmaps.lock.json", ".roadmap/plugin-inputs/", ".roadmap/snapshots/", "docs/spec/", "docs/qa/"):
        assert path not in tracked
        assert path in generated


def test_reference_uses_current_file_effect_recovery_command(repo_root: Path) -> None:
    text = (repo_root / "docs/guides/esaa-cli-reference.en.md").read_text(encoding="utf-8")
    assert "esaa effects recover" in text
    legacy_command = "esaa " + "recover" + "-file-effects"
    assert legacy_command not in text
