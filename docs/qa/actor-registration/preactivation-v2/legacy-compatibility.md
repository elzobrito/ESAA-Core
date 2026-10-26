# Compatibilidade legada

Workspace sem `actor.bootstrap` permanece `identity_contract=inactive`. Review `qa_role` com `authorization=None` continua aceita. `scope_patch` absoluto histórico emite `LEGACY_SCOPE_PATCH_UNSAFE`; novas escritas inseguras seguem rejeitadas. Pin v1 não migra automaticamente para v2.
