# Suíte completa

Comando: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider`

Resultado 2026-10-26: **593 passed, 4 skipped in 94.97s**.

Os 4 skipped são os testes Docker opcionais sem `ESAA_TEST_DOCKER`. Closeout anterior reportou 597 com Docker habilitado; a diferença são esses skips, não falhas.
