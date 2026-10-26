# Regressão negativa

Suíte observada: `tests/test_canonical_identity.py`, `tests/test_trust_rollback.py`, `tests/test_signed_replay.py`, `tests/test_closeout_authorization.py`, `tests/test_actor_registration.py` — 107 passed.

Casos: aliases X/Y/Z do mesmo principal; B complete A = LOCK_VIOLATION; self-review por alias = SELF_REVIEW_FORBIDDEN; unsigned pós-bootstrap = ACTOR_AUTH_FAILED; legado unsigned após ativação = PRINCIPAL_UNBOUND; authorization fornecida inativa = ACTOR_BOOTSTRAP_REQUIRED; joint swap = TRUST_MISMATCH; prebootstrap rollback = TRUST_ROLLBACK.
