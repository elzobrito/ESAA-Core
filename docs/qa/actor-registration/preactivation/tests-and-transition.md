# Execuções reais e transição

Cwd /home/elzobrito/desenvolvimento/ESAA-Core. Ambiente PYTHONDONTWRITEBYTECODE=1, PYTHONPATH=src, Python -B; cache pytest desabilitado. Nenhuma instalação/download.

## Suíte completa — executor do pacote

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -B -m pytest -q -p no:cacheprovider --basetemp /tmp/esaa-preactivation-fullsuite-20261002`

433 passed in 27.20s; exit 0. Resultado observado nesta revisão, não apenas relato anterior.

## Avaliador independente de implementação

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -B -m pytest tests/test_actor_registration.py -q -p no:cacheprovider`

16 passed in 2.66s.

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -B -m pytest /tmp/esaa-preactivation-review-DeVHiv/test_pre_activation.py -q -s -p no:cacheprovider`

Saída:

```text
INVALID_SIGNATURES_ACCEPTED ['actor.bootstrap', 'actor.register', 'review']
REPLACEMENT_ANCHOR_ACCEPTED
UNSIGNED_QA_FALLBACK_ACCEPTED_AFTER_ROLLBACK
CLAIM_COMPLETE_UNSIGNED_ALIAS_ACCEPTED_AND_APPROVED
4 passed in 0.95s
```

Para reprodução futura: fixture-reproductions.py contém o teste exato, referência absoluta repo/fixtures. Executá-lo com pytest em scratch, nunca editar event store real. Todas as escritas do teste atingem somente tmp_path; chaves são descartáveis e não publicadas.

Transição: inactive usa RUNTIME_POLICY review_authorization=qa_role; active com histórico íntegro chama assert_review_identity e não tem catch/fallback. Assinatura inválida nesse ramo é rejeitada. Entretanto active é calculado exclusivamente pela presença de bootstrap no event store: apagar identidade permite ramo legacy. Ausência de principal assinado para claim/complete permite alias mesmo no ramo active. Por isso a afirmação “sem fallback após ativação” não vale contra o adversário solicitado.
