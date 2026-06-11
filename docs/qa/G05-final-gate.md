# QA G05 - Final gate do roadmap token-fixes

**Task:** T-2042  
**Valida:** G05 e fechamento do roadmap token-fixes  
**Resultado:** APROVADO

## Escopo Validado

- G03 foi fechado: `T-2021` e `T-2022` estao `done`.
- G05 foi implementado: `T-2041` esta `done`.
- O gate de formatacao ampla foi formalizado em `T-2050`.
- A limpeza final de mojibake foi formalizada em `T-2051`.

## Evidencias

### Suite completa

```powershell
$env:PYTHONPATH='src'; python -m pytest -q
```

Resultado:

```text
318 passed in 62.07s
```

### Auditoria critica

```powershell
$env:PYTHONPATH='src'; python tools/audit/critical_findings.py --root .
```

Resultado:

```text
total_findings: 0
EXIT=0
```

### Black

```powershell
python -m black --check src/esaa tools/audit
```

Resultado:

```text
46 files would be left unchanged
```

### Ruff seletivo

```powershell
python -m ruff check src/esaa tools/audit tests --select F403,F405,F821
```

Resultado:

```text
All checks passed!
```

### Smoke import e versao

```powershell
$env:PYTHONPATH='src'; python -c "import esaa.service as s; print(s.ESAAService.__name__)"
$env:PYTHONPATH='src'; python -m esaa --version
```

Resultado:

```text
ESAAService
esaa 0.5.0b5 (protocol 0.4.1, esaa 0.4.x)
```

## Greps de Fechamento

```powershell
rg -n "service_common|noqa: F403|noqa: F405" src tests
```

Resultado: `NO_MATCH`.

```powershell
Test-Path src\esaa\service_common.py
```

Resultado: `False`.

```powershell
rg -n "lstrip" src/esaa/utils.py tests
```

Resultado: `NO_MATCH`.

## Boundary e Contrato Vivo

O boundary temporario foi revertido. O contrato vivo em `.roadmap/AGENT_CONTRACT.yaml` voltou a permitir `impl.write` apenas para:

```text
src/**
tests/**
```

A semantica de edits permaneceu sincronizada no contrato vivo: `base_sha256` contra conteudo commitado em disco, segunda escrita no mesmo path dentro do mesmo `run()` rejeitada com `WRITE_CONFLICT`, e match de `old_string` contra texto UTF-8 com newlines exatos.

## Observacao Operacional

`src/esaa/service_common.py` foi removido fisicamente e nao ha referencias remanescentes. O schema atual de `file_updates` nao possui uma operacao de delete; por isso a remocao foi validada por `Test-Path` e pelos greps, enquanto os arquivos modificados foram registrados nas tasks governadas.

## Conclusao

G05 esta aprovado. O barril `service_common.py` deixou de existir, os imports curinga `F403/F405` sumiram do nucleo, a suite completa esta verde, a auditoria critica retorna zero findings e o boundary temporario foi restaurado.
