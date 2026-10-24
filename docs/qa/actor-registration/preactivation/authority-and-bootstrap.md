# Interface implementada — referência, NÃO autorização para ativar

Versão observada: 0.5.0b19, PYTHONPATH=src para selecionar implementação dirty. Instalação distribuída ainda não verificada; packaging pendente. Estado real inactive. Não executar os comandos mutantes abaixo antes de resolver request_changes e provisionar autoridade externa pelo proprietário.

## Comandos existentes (descobertos por --help)

```bash
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core actor show
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor bootstrap --authorization /CAMINHO/owner-bootstrap.json --dry-run
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor bootstrap --authorization /CAMINHO/owner-bootstrap.json
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor register --actor-id ID --role qa --scope review --actor-public-key HEX_PUBLICO --authorization /CAMINHO/owner-register.json --dry-run
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core --runner human-terminal actor register --actor-id ID --role qa --scope review --actor-public-key HEX_PUBLICO --authorization /CAMINHO/owner-register.json
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core actor show
PYTHONPATH=src python -B -m esaa --root /home/elzobrito/desenvolvimento/ESAA-Core verify
```

Runner textual carimba proveniência, NÃO credencial. actor show é o único comando de consulta registry; actor list não existe. Não existe comando CLI para gerar chave, assinar autorização ou provisionar âncora protegida. Não inventar tais comandos. A assinatura deve ser produzida pelo proprietário fora do alcance dos agentes, após remediação e procedimento externo de confiança definido. Nenhuma chave definitiva foi gerada aqui.

## Arquivos e contrato real

Âncora atual: .roadmap/governance-anchor.json, JSON alg=ed25519, public_key_hex (32 bytes hex), fingerprint_sha256=SHA256 bytes públicos. Código load_anchor não comprova proteção externa desse arquivo. Chave privada nunca deve entrar no workspace/artefatos.

Autorização JSON: objeto payload e signature_hex (64 bytes hex). payload contém alg=ed25519, nonce hex >=16 bytes, operation, project_id=fingerprint da chave owner, scope. Canonicalização em utils.canonical_json_bytes: json.dumps ensure_ascii=False, sort_keys=True, separators=(',', ':') + newline, UTF-8. Assina bytes canônicos do payload, não envelope.

Scope bootstrap: public_key_hex e fingerprint_sha256 da âncora. Scope cadastro: actor_id, role, authorization_scope (ex.: ['review']), actor_public_key_hex. Cadastro assinado pelo owner; public key QA distinta da chave owner. Scope review: actor_id, task_id, decision; assinatura QA com nonce novo. Nomes/prefixos não provam principal. Roles aceitos qa/specification/implementation; o escopo hoje é lista textual, não prova automática de isolamento cross-project.

ActorAdminMixin anexa actor.bootstrap/register via _commit_orchestrator_events. project_registry reconstrói atores dos eventos; replay/verify não autentica essas assinaturas (R1). Não editar registry/projeção manualmente.

## Aceitação posterior exigida

Após correção/revisão/empacotamento e provisionamento humano, conferir actor show ativo, recibos de eventos, verify, cadastro com assinatura válida, negativa de assinatura inválida sem evento, nonce replay e revisão independente. Testar também rollback/substituição conjunta, pois verify ok sozinho não prova autenticidade hoje. Fazer negativas em fixtures, nunca adulterar estado real. Aceitação real deve ser outra execução documentada; os 433 testes com chaves descartáveis não a substituem. Esta referência NÃO torna o bootstrap atual seguro para produção.
