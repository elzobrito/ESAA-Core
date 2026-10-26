# Empacotamento

PACKAGING-001 done. `pyproject.toml` declara `cryptography>=42.0.0`. Artefatos locais provisórios em `docs/qa/actor-registration/packaging/reconciliation.json`:

- wheel sha256 `74684e657d2b77f3a55c8ee2582fa33ad6f47d3b266a460bd93d9d129656f9c9`
- sdist sha256 `9c55e26c57672d2d3f3bbbc05e77beae98155055c6b849233d16c4a6184bc361`
- twine check passed

Esses hashes são do candidato local. Publicação PyPI exige rebuild do commit aprovado e comparação com hashes públicos.
