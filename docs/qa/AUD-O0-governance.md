# AUD-O0-070 — Propriedades de governança da Onda 0

- **Origem:** achado ENG-03 de `docs/audit/ESAA-CORE-AUDIT-2026-11-10.md`: a suíte passava (652 testes) com GOV-01, GOV-02, GOV-05, SEC-01 e SEC-03 presentes.
- **Entrega:** `tests/test_governance_properties.py`, um teste por propriedade.
- **Data da execução:** 2026-11-11, Python 3.14.4, Linux.

## Propriedades cobertas

| Teste | Propriedade | Achado | Tarefa que corrigiu |
|---|---|---|---|
| `test_p1_reviewer_runner_must_differ_from_executor_when_enforced` | Com `review_runner_separation: enforce`, o runner que fez claim/complete não revisa a tarefa | GOV-01 | AUD-O0-020 |
| `test_p2_claim_requires_dependencies_done` | `claim` exige todas as dependências em `done` | GOV-02 | AUD-O0-010 |
| `test_p3_verify_detects_tampered_projections` | `verify` acusa `roadmap.json`, `lessons.json` ou `issues.json` adulterados | GOV-05 | AUD-O0-060 |
| `test_p4_agent_lesson_stays_out_of_dispatch_context` | Lesson enviada por agente fica `proposed` e não entra no `dispatch-context` | SEC-01 | AUD-O0-030 |
| `test_p5_file_effects_cannot_escape_root_through_symlink` | Symlink em `src/` não leva escrita para fora do workspace e nenhum evento é gravado | SEC-03, GOV-08 | AUD-O0-050 |

Cada teste reproduz o ataque pela API pública do serviço e afirma também o caminho legítimo
(revisão por outro runner, claim após a dependência concluir, `verify` voltando a `ok`,
escrita normal em diretório novo).

O arquivo usa somente a API que já existia antes da Onda 0 (códigos de erro como texto, sem
importar módulos novos). Por isso o mesmo arquivo roda, sem alteração, contra o commit
pré-auditoria.

## Evidência: falha no commit `d741770`, sucesso no candidato

### Commit `d741770` (pré-auditoria)

Preparação: `git archive d741770 | tar -x -C <dir>`; cópia de
`tests/test_governance_properties.py` para `<dir>/tests/`.

```text
$ PYTHONPATH=src python3 -B -m pytest -q -p no:cacheprovider tests/test_governance_properties.py
E       Failed: DID NOT RAISE ESAAError                      (p1: review com o mesmo runner aceito)
E       Failed: DID NOT RAISE ESAAError                      (p2: claim com dependência em todo aceito)
E           AssertionError: roadmap.json
E           assert 'ok' == 'mismatch'                        (p3: verify ok com projeção adulterada)
E       AssertionError: assert ['active'] == ['proposed']    (p4: lesson de agente nasce active)
E           Failed: DID NOT RAISE ESAAError                  (p5: escrita através do symlink aceita)
FAILED tests/test_governance_properties.py::test_p1_reviewer_runner_must_differ_from_executor_when_enforced
FAILED tests/test_governance_properties.py::test_p2_claim_requires_dependencies_done
FAILED tests/test_governance_properties.py::test_p3_verify_detects_tampered_projections
FAILED tests/test_governance_properties.py::test_p4_agent_lesson_stays_out_of_dispatch_context
FAILED tests/test_governance_properties.py::test_p5_file_effects_cannot_escape_root_through_symlink
5 failed in 1.95s
```

### Candidato (branch `audit/onda-0`, com AUD-O0-010 a AUD-O0-060 aplicadas)

```text
$ PYTHONPATH=src python3 -B -m pytest -q -p no:cacheprovider tests/test_governance_properties.py
.....                                                                    [100%]
5 passed in 2.20s

$ PYTHONPATH=src python3 -B -m pytest -q -p no:cacheprovider
741 passed, 4 skipped
```

Antes desta tarefa a suíte tinha 736 testes passando; os 5 novos são os deste arquivo.

## Limites

- **P1 depende de opt-in.** A separação por runner só vale com `review_runner_separation: enforce`
  na política; o padrão é `off` (decisão do operador em 2026-11-10). O teste liga a política
  explicitamente; ele não prova nada sobre workspaces que não optaram, incluindo este repositório.
- **Runner e actor são autodeclarados.** P1 mostra que uma sessão única não se autoaprova
  por engano; não mostra resistência a um agente que troque `--runner` de propósito. Isso
  depende da identidade assinada, que continua inativa.
- **P5 é POSIX.** O teste é pulado fora de POSIX; Windows não foi validado.
- **P5 não cobre corrida.** Uma troca por symlink entre a validação e o commit é barrada no
  commit, depois do append (resíduo de GOV-08 registrado na AUD-O0-050).
- **Fora do escopo deste arquivo:** comandos de operador (`OPERATOR_REQUIRED`), trilha do
  `activity clear` e impersonação do orchestrator têm testes próprios em
  `tests/test_operator_commands.py` e `tests/test_cli_operator_commands.py`, mas não foram
  incluídos entre as cinco propriedades pedidas.
- **GOV-03 e GOV-04 continuam abertos por padrão:** só valem com `runner_validation: strict`.
