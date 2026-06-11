# QA G04 - Gate de auditoria com exit code real (B1)

**Task:** T-2032  
**Valida:** T-2031 contra docs/spec/G04-audit-gate.md  
**Resultado:** APROVADO

## Evidencias

### 1. Testes focados

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_audit_critical_findings.py -q
```

Resultado:

```text
13 passed
```

Cobertura confirmada:

- `main()` retorna `0` contra o repo real limpo.
- `main()` retorna `1` contra diretorio vazio com findings.
- Inventario `CHECKS` permanece com 9 checkers.
- Checkers criticos seguem retornando limpos contra o repo.

### 2. Auditor contra o repo real

```powershell
$env:PYTHONPATH='src'; python tools/audit/critical_findings.py --root .
$LASTEXITCODE
```

Resultado observado:

```text
total_findings: 0
EXIT=0
```

O gate permanece verde quando o repo esta limpo.

### 3. Auditor contra diretorio vazio

```powershell
$tmp = New-Item -ItemType Directory ...
$env:PYTHONPATH='src'; python tools/audit/critical_findings.py --root $tmp.FullName
$LASTEXITCODE
```

Resultado observado:

```text
total_findings: 8
EXIT=1
```

O gate agora falha corretamente quando ha findings, cobrindo o B1.

### 4. Lint e formatacao no escopo tocado

```powershell
python -m ruff check tools/audit/critical_findings.py tests/test_audit_critical_findings.py
python -m black --check tools/audit/critical_findings.py tests/test_audit_critical_findings.py
```

Resultado:

```text
All checks passed!
2 files would be left unchanged.
```

### 5. Verificacao ESAA

Apos a aplicacao governada de T-2031 e antes desta conclusao de QA:

```powershell
python -m esaa --root . verify
```

Resultado:

```text
verify_status: ok
```

## Criterios de aceitacao

| Criterio | Status |
|---|---|
| Auditor retorna exit 0 quando `total_findings == 0` | OK |
| Auditor retorna exit 1 quando `total_findings > 0` | OK |
| Testes cobrem repo real e diretorio vazio | OK |
| Tests focados verdes | OK - 13 passed |
| Ruff/Black no escopo tocado | OK |
| ESAA verify | OK |

## Observacao operacional

A execucao de T-2031 exigiu liberacao temporaria de `tools/**` no boundary vivo de `impl`, conforme previsto no roadmap. Essa liberacao ainda esta presente em `.roadmap/AGENT_CONTRACT.yaml` e deve ser revertida pelo operador quando a janela de tasks que escrevem em `tools/**` terminar.
