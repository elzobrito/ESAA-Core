# G04 - Gate de auditoria com exit code real (B1)

## Problema

`tools/audit/critical_findings.py` imprime os findings corretamente, mas `main()` retorna sempre sucesso:

```python
return 0 if result["total_findings"] == 0 else 0
```

Isso transforma o checker em um relatorio informativo, nao em um gate. Em CI ou em scripts de operador, um diretorio quebrado pode produzir findings e ainda assim encerrar com exit code 0.

## Semantica alvo

1. `main()` deve retornar `0` somente quando `result["total_findings"] == 0`.
2. `main()` deve retornar `1` quando houver qualquer finding.
3. A saida JSON deve permanecer identica: o contrato de leitura humana e automacao continua em `run_checks(root)` e no JSON impresso.
4. `run_checks(root)` nao muda. A correcao e somente no codigo de saida do comando.

Implementacao alvo:

```python
return 0 if result["total_findings"] == 0 else 1
```

## Casos de teste

Adicionar cobertura em `tests/test_audit_critical_findings.py`:

| Cenario | Setup | Resultado esperado |
|---|---|---|
| Repo real limpo | `sys.argv = ["critical_findings.py", "--root", str(REPO_ROOT)]` | `main() == 0` |
| Diretorio vazio | `sys.argv = ["critical_findings.py", "--root", str(tmp_path)]` | `main() == 1` |

O diretorio vazio e suficiente porque faltam fontes canonicas (`.roadmap/AGENT_CONTRACT.yaml`, `src/esaa/store.py`, `src/esaa/file_effects.py`, etc.), entao `run_checks(tmp_path)` deve gerar findings sem precisar de fixture elaborada.

## Criterios de aceitacao

1. `tools/audit/critical_findings.py` retorna exit code 1 quando `total_findings > 0`.
2. `tests/test_audit_critical_findings.py` cobre `main() == 0` no repo real e `main() == 1` em `tmp_path` vazio.
3. `python tools/audit/critical_findings.py --root .` continua imprimindo `total_findings: 0` e sai com codigo 0 quando o repo esta limpo.
4. Um comando equivalente contra diretorio vazio sai com codigo 1.
5. Nenhum checker novo e introduzido nesta task; `CHECKS` permanece com o mesmo inventario.

## Impacto operacional

Depois da implementacao, o auditor deixa de ser decorativo: scripts e CI podem falhar corretamente quando qualquer achado critico reaparecer. Isso tambem protege o roadmap token-fixes, porque o gate final G05 passa a depender de um codigo de saida real, nao apenas da leitura manual do JSON.
