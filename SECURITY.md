---
titulo: "Política de segurança e compatibilidade do ESAA-Core"
tipo: "Política"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex — agente de especificação (agent-spec)"
status: "Em revisão"
instituicao: "ESAA-Core"
departamento: "Projeto ESAA"
---

# Política de segurança e compatibilidade do ESAA-Core

**Sumário:** Reporte privado · Suporte · Modelo de ameaças · Compatibilidade · Referências.

| Versão | Data | Autoria | Descrição |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex (agent-spec) | Registro inicial da AUD-O2-090; revisão independente pendente. |

## 1. Reporte privado de vulnerabilidades

O canal previsto é o mecanismo **Private vulnerability reporting** do repositório [elzobrito/ESAA-Core — Security](https://github.com/elzobrito/ESAA-Core/security). Quando habilitado pelo proprietário, o botão **Report a vulnerability** permite enviar relato privado; não publique segredos, chaves ou dados sensíveis em issues públicas.

**Decisão pendente do proprietário:** a consulta autenticada à API do GitHub em 12/11/2026 retornou `enabled=false` para o reporte privado. Portanto, o canal ainda precisa ser habilitado em Settings → Security and quality → Advanced Security → Private vulnerability reporting. Esta política não cria outro canal nem inventa endereço de e-mail. Até a habilitação, a disponibilidade de um canal privado permanece pendente; uma issue pública, se necessária para sinalizar indisponibilidade do canal, deve limitar-se ao pedido de contato, sem detalhes da vulnerabilidade.

**Prazo esperado de resposta:** proposta de confirmação inicial em até **7 dias úteis** após recebimento pelo canal privado, sujeita à confirmação do proprietário junto à habilitação. Ainda não há SLA aprovado nem prazo garantido de correção. Prioridade e coordenação da divulgação dependem de impacto, reprodutibilidade e capacidade de manutenção. Essa decisão deve constar no fechamento da AUD-O2-090.

Inclua versão instalada, plataforma, modo de identidade/cadeia, condições necessárias, impacto e passos mínimos de reprodução com dados fictícios. O mantenedor poderá pedir evidências adicionais pelo mesmo relato privado.

## 2. Versões suportadas

Somente a **beta publicada mais recente** recebe avaliação e correções de segurança. Betas anteriores não recebem backports garantidos; ao reportar em uma delas, informe a versão e, quando possível, reproduza também na mais recente. Consulte a versão disponível em [PyPI — esaa-core](https://pypi.org/project/esaa-core/), sem assumir que a versão deste documento continuará sendo a última.

## 3. Modelo de ameaças e premissas

O escopo canônico está em [modelo-ameacas](docs/security/threat-model.md). Ele abrange integridade do histórico e das projeções, ownership, autorização de review, boundaries, identidade opcional e integridade dos bytes finais dos efeitos. Orchestrator, sistema operacional, biblioteca criptográfica, configuração autorizada, custódia de chaves e registros externos protegidos integram a base confiável.

Identidade inativa, proveniência declarada e cadeia opcional sem chave são modos arquiteturais suportados, com as garantias de [adr-0001](docs/adr/0001-identidade-opt-in.md) e [adr-0003](docs/adr/0003-cadeia-opcional-sem-chave.md). Habilitar registro estrito de runners não autentica posse de chave. Ed25519 e pin externo exigem configuração explícita e isolamento real; permissões de diretório não asseguram isolamento de agente que compartilha o UID do proprietário.

Não se promete resistência a host, proprietário, processo do Orchestrator ou chaves comprometidos; nem que a cadeia local impeça reescrita com recálculo por quem tem escrita. Execução de plugins ou checks não constitui sandbox universal, e suporte a concorrência local não assegura coordenação entre hosts via montagem. Backup de artifacts é requisito operacional para recuperar bytes após perda ou clone, conforme [backup-artifacts](docs/operations/artifact-backup.md). Este texto não certifica implantação em produção nem substitui revisão independente do modo ativado.

## 4. Compatibilidade entre betas

Entre betas podem mudar API Python, opções CLI, interfaces de plugin, defaults, schemas de configuração e formato de projeções. Atualizações podem exigir migração explícita e atualização de consumidores; leia as instruções da release e preserve backups antes de migrar. Projeções são reconstruíveis e não são uma API estável entre betas.

A política do projeto é preservar a **reprojeção de logs válidos produzidos por versões publicadas**: uma versão posterior deve conseguir lê-los pelas regras históricas e transformações de formato aplicáveis, sem reescrever o log nem exigir o schema novo por ação durante replay. Logs corrompidos, versões futuras desconhecidas e dependências externas perdidas não ganham validade por essa garantia. Leitor antigo não recebe garantia de ler formato futuro; uma atualização de formato deve falhar de forma explícita e orientar atualização do leitor.

[adr-0008](docs/adr/0008-schema-append-upcasters.md) define a implementação proposta de schemas no append, upcasters e fixtures produzidas por releases, sob AUD-O2-050. [adr-0002](docs/adr/0002-hash-projecao-versionado.md) define compromissos de hash por versão do projetor, sob AUD-O2-070. A garantia de suporte é compromisso de manutenção; a cobertura sistemática dessas versões e o novo mecanismo ainda são entregas propostas, não recursos já concluídos pela documentação. Mudança intencional de saída do projetor requer atualizar sua própria versão quando a AUD-O2-070 for implementada; hashes de versões diferentes não serão falsamente comparados.

## Referências

**Este documento referencia:**

- [modelo-ameacas](docs/security/threat-model.md) — ativos, autoridades, controles e não garantias.
- [adr-0001](docs/adr/0001-identidade-opt-in.md) e [adr-0003](docs/adr/0003-cadeia-opcional-sem-chave.md) — modos opcionais e confiança.
- [adr-0002](docs/adr/0002-hash-projecao-versionado.md) e [adr-0008](docs/adr/0008-schema-append-upcasters.md) — evolução compatível do formato.
- [backup-artifacts](docs/operations/artifact-backup.md) — preservação de bytes recuperáveis.
- [GitHub Docs — Configurar reporte privado](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository) — configuração do mecanismo pelo proprietário.

**Este documento é referenciado por:**

- [indice-adrs](docs/adr/README.md) — índice arquitetural.
