# Reprodução

1. `PYTHONPATH=src python -B -m pytest tests/test_canonical_identity.py tests/test_trust_rollback.py tests/test_closeout_authorization.py tests/test_signed_replay.py tests/test_actor_registration.py -q`
2. Esperado: 107 passed.
3. `PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core actor show` → identity_contract inactive.
4. Não executar bootstrap.
