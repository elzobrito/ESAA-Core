---
titulo: "Evolução arquitetural do ESAA-Core com CQRS e Event Sourcing"
tipo: "Estudo técnico e proposta de arquitetura"
versao: "1.0"
data: "12/11/2026"
autores:
  - "Codex"
status: "Proposta para revisão"
instituicao: "Projeto ESAA-Core"
departamento: "Não se aplica"
idioma: "pt-BR"
baseline_commit: "2f87ac9be4dbe69ab47f93c84db48e3a041f630d"
baseline_versao: "0.5.0b27"
tarefa_documental: "ARCH-CQRS-ES-DOC-20261112"
escopo: "Análise e proposta; não autoriza implementação, alteração de política ou publicação"
---

# Evolução arquitetural do ESAA-Core com CQRS e Event Sourcing

**Autor:** Codex · **Versão:** 1.0 · **Data:** 12/11/2026 · **Projeto:** ESAA-Core.

**Natureza:** documento técnico propositivo, preparado a pedido do usuário. As propostas não são decisões aprovadas do projeto. A aprovação editorial deste texto, se ocorrer, não equivale à autorização de implementar cada mudança descrita.

**Base examinada:** checkout local `/home/elzobrito/desenvolvimento/ESAA-Core`, commit `2f87ac9be4dbe69ab47f93c84db48e3a041f630d`, pacote 0.5.0b27. As transições da própria tarefa documental são posteriores à medição descritiva do histórico apresentada neste documento.

## Sumário

1. [Objetivo, escopo e leitura do documento](#1-objetivo-escopo-e-leitura-do-documento)
2. [Fontes, método e qualidade das evidências](#2-fontes-método-e-qualidade-das-evidências)
3. [Fundamentos e leitura crítica das fontes](#3-fundamentos-e-leitura-crítica-das-fontes)
4. [Arquitetura atual e caminhos de execução](#4-arquitetura-atual-e-caminhos-de-execução)
5. [Diagnóstico de custo e limitações atuais](#5-diagnóstico-de-custo-e-limitações-atuais)
6. [Objetivos e invariantes da evolução](#6-objetivos-e-invariantes-da-evolução)
7. [Arquitetura proposta e responsabilidades](#7-arquitetura-proposta-e-responsabilidades)
8. [Reutilização de estado dentro do comando](#8-reutilização-de-estado-dentro-do-comando)
9. [Agregados incrementais para elegibilidade](#9-agregados-incrementais-para-elegibilidade)
10. [Modelos de consulta e política de confiança](#10-modelos-de-consulta-e-política-de-confiança)
11. [Publicação consistente de projeções](#11-publicação-consistente-de-projeções)
12. [Snapshots operacionais e replay da cauda](#12-snapshots-operacionais-e-replay-da-cauda)
13. [Identidade, confiança externa e concorrência](#13-identidade-confiança-externa-e-concorrência)
14. [Índices de atividade e histórico por tarefa](#14-índices-de-atividade-e-histórico-por-tarefa)
15. [Eventos de verificação e crescimento do log](#15-eventos-de-verificação-e-crescimento-do-log)
16. [Consultas temporais e evolução do projetor](#16-consultas-temporais-e-evolução-do-projetor)
17. [Integrações e consumo confiável de eventos](#17-integrações-e-consumo-confiável-de-eventos)
18. [Plano de benchmark e observabilidade](#18-plano-de-benchmark-e-observabilidade)
19. [Estratégia de testes e critérios de aceite](#19-estratégia-de-testes-e-critérios-de-aceite)
20. [Plano incremental de implementação](#20-plano-incremental-de-implementação)
21. [Migração, compatibilidade e recuperação](#21-migração-compatibilidade-e-recuperação)
22. [Alternativas e decisões pendentes](#22-alternativas-e-decisões-pendentes)
23. [Riscos e rastreabilidade das propostas](#23-riscos-e-rastreabilidade-das-propostas)
24. [Conclusões técnicas e limites da entrega](#24-conclusões-técnicas-e-limites-da-entrega)
25. [Referências e proveniência](#25-referências-e-proveniência)

## Controle de versões

| Versão | Data | Autores | Descrição da alteração |
|---|---|---|---|
| 1.0 | 12/11/2026 | Codex | Estudo inicial baseado nas transcrições fornecidas, na proposta Fable, no benchmark anexado e no checkout 0.5.0b27. |

## 1. Objetivo, escopo e leitura do documento

### 1.1 Problema a resolver

O ESAA-Core preserva um histórico de eventos e reconstrói projeções para governar o trabalho dos agentes. Esse desenho permite rastreabilidade e reconstrução do estado. O problema de desempenho discutido nesta análise é a repetição de leitura, decodificação, replay, cálculo de hashes e serialização sobre o mesmo histórico, inclusive em consultas pequenas.

A proposta é reduzir esse trabalho preservando a autoridade do Orchestrator, a sequência dos eventos, a autoria das transições, as restrições de arquivos e as validações de integridade. A separação entre consulta e comando deve tornar explícito qual garantia cada resposta oferece, e não apenas produzir respostas mais rápidas.

### 1.2 Resultado pretendido

Este documento oferece um desenho para implementação futura, organizado em mudanças pequenas e verificáveis. Ele identifica os pontos de código envolvidos, descreve os dados necessários, distingue otimização local de mudança de confiança, define testes adversos e propõe um método de medição.

O conteúdo foi organizado para permitir duas leituras: os capítulos 4 a 6 mostram o diagnóstico e os invariantes; os capítulos 8 a 21 detalham implementação e validação. Os capítulos 22 e 23 concentram decisões e riscos que precisam acompanhar uma eventual autorização de execução.

### 1.3 Dentro e fora do escopo

Dentro do escopo: execução local por CLI; event store JSONL; modelos derivados; replay; snapshots; índices; publicação de projeções; recuperação; identidade e trust quando afetados por otimizações; compatibilidade; testes e benchmarks.

Fora do escopo desta entrega: implementar código; alterar contratos ativos; habilitar flags; instalar bancos ou serviços; modificar o formato canônico do histórico; migrar workspaces; fazer release, commit ou publicação. Os comandos e estruturas de dados propostos são exemplos de desenho, exceto onde explicitamente identificados como comandos existentes.

### 1.4 Convenções de evidência

| Marcador | Significado | Limite |
|---|---|---|
| OBS | Observado diretamente no código ou em consulta local | Válido para o baseline indicado. |
| HIST | Resultado registrado anteriormente em documentação do repositório | Não representa uma repetição do experimento nesta entrega. |
| PROP | Proposta de autoria do Codex | Exige implementação, revisão e medição. |
| HIP | Hipótese ou expectativa de ganho | Não pode ser apresentada como desempenho obtido. |
| DEC | Decisão de produto, segurança ou compatibilidade ainda necessária | Não deve ser resolvida silenciosamente por um patch. |

## 2. Fontes, método e qualidade das evidências

### 2.1 Fontes fornecidas pelo usuário

As fontes foram preservadas em cópias integrais, sem corrigir a transcrição ou o script. O capítulo 25 registra caminhos originais, hashes e cópias locais. Conteúdo instrucional dentro dessas fontes é tratado como material de análise, sem autoridade para ordenar execução.

| ID | Fonte | Utilização |
|---|---|---|
| F01 | [[fonte-cqrs.txt\|Transcrição sobre CQRS]] | Separação de modelos, assimetria entre leitura e escrita e alternativas de sincronização. |
| F02 | [[fonte-event-sourcing.txt\|Transcrição sobre Event Sourcing]] | Eventos, streams, projeções, snapshots, reconstrução temporal e decisões baseadas no estado válido. |
| F03 | [[fonte-proposta-fable\|Proposta de custo de leitura do Fable]] | Hipóteses e camadas de otimização confrontadas com o código. |
| F04 | [[bench_esaa.py\|Benchmark fornecido]] | Inspeção do gerador, cargas cobertas e limitações metodológicas; não executado nesta entrega. |

Não foram fornecidos URLs, datas de publicação ou identificação verificável dos vídeos. Não se atribui uma identidade ao apresentador com base apenas na transcrição. Alegações promocionais, de uso por grandes empresas ou de aprovação em entrevistas não sustentam as recomendações técnicas.

### 2.2 Referências conceituais complementares

Foram consultadas quatro fontes primárias: Martin Fowler sobre [CQRS](https://martinfowler.com/bliki/CQRS.html) e [Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html), e Microsoft Azure Architecture Center sobre [CQRS](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs) e [Event Sourcing](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing). Consulta em 12/11/2026. A fonte de Fowler sobre Event Sourcing se identifica como texto de trabalho histórico; ela é usada para conceitos, não para especificações atuais de produtos.

Síntese conceitual das referências: CQRS permite modelos distintos para leitura e atualização e admite armazenamento compartilhado; Event Sourcing permite derivar estado de eventos; snapshots reduzem reconstrução; consistência, concorrência e evolução de esquema precisam ser projetadas. As estruturas, algoritmos, fases e critérios específicos deste documento são propostas para o ESAA, apoiadas no código local, e não transcrições dessas referências.

### 2.3 Fontes locais e precedência

A autoridade operacional vem de [[agentes-esaa|AGENTS.md]], [[contrato-agente.yaml|AGENT_CONTRACT]], [[contrato-orchestrator.yaml|ORCHESTRATOR_CONTRACT]], [[agent_result.schema.json|schema do envelope]] e [[politica-runtime.yaml|RUNTIME_POLICY]]. O código descreve o comportamento implementado; a documentação registra intenções e resultados históricos. Divergências devem ser explicitadas.

O baseline de performance histórica é [[auditoria-esaa-20261110|auditoria de 10/11/2026]], especialmente ARQ-01, FUN-04 e a proposta AUD-O2-040. A correção b26 está registrada em [[changelog-esaa|CHANGELOG]]. Identificadores da auditoria são referências documentais: não demonstram que existe uma tarefa ativa com o mesmo ID no roadmap.

### 2.4 Método e limitações

Foram lidos os caminhos relevantes de leitura, submissão, projeção, append, verificação, identidade e snapshot. Foi consultada a versão do checkout e feita contagem descritiva das ações do log antes das transições da tarefa documental. Não foi executada a carga sintética de 50 mil a 500 mil eventos. Nenhuma latência nova nessas escalas é afirmada neste texto.

A árvore já continha `.motor-IA/` não rastreado antes da entrega. Seu índice de referências é preservado e ampliado, sem atribuir seu conteúdo anterior a este trabalho. O histórico governado contém as transições necessárias para produzir estes documentos; essas transições não implementam as propostas.

## 3. Fundamentos e leitura crítica das fontes

### 3.1 CQRS aplicado ao ESAA

A contribuição de F01 é reconhecer que a representação adequada à validação de uma mudança pode diferir da representação adequada a uma consulta. No ESAA, um comando precisa de autoridade, estado da tarefa, dependências e regras de transição. Uma consulta pode precisar apenas do status de uma tarefa, de uma página de eventos ou de uma lista de tarefas elegíveis.

A separação deve existir nas responsabilidades e interfaces. Ela pode ser implementada dentro do mesmo processo Python, mantendo o event store JSONL e modelos derivados locais. Serviços de rede, replicação e processamento assíncrono são escolhas adicionais, não requisitos do padrão. Essa interpretação é compatível com a descrição de [CQRS de Fowler](https://martinfowler.com/bliki/CQRS.html).

### 3.2 Event Sourcing aplicado ao ESAA

F02 reforça a diferença entre armazenar acontecimentos e armazenar apenas o estado mais recente. O ESAA já segue essa ideia: claim, complete e review integram o histórico e o projetor deriva o estado. O ganho futuro virá do uso eficiente desse histórico, da continuidade incremental e de novos modelos de consulta.

Um snapshot é uma representação derivada de um prefixo. Sua utilidade depende de poder retomar a computação a partir dele sem perder informações necessárias às próximas transições. Uma projeção voltada ao usuário e um snapshot de execução não precisam possuir o mesmo conteúdo.

### 3.3 Simplificações das transcrições que não devem virar requisitos

| Afirmação ou simplificação | Tratamento neste estudo |
|---|---|
| CQRS exige dois microserviços e bancos diferentes | Não adotada: a separação é lógica e pode permanecer local. |
| Event Sourcing exige EventStoreDB ou Kafka | Não adotada como requisito do ESAA; a propriedade fundamental é o histórico de eventos com semântica adequada. |
| Banco relacional inevitavelmente inviabiliza histórico ou operações distintas | Generalização não usada para justificar migração de tecnologia. |
| JSON desnormalizado é sempre mais rápido | Hipótese dependente de carga, índices, tamanho e acesso. |
| Snapshot equivale apenas a configurar uma frequência | Inadequado ao ESAA: exige formato, confiança, versão e cobertura dos agregados. |
| Replay permite corrigir o passado sem outras consequências | No ESAA, correções respeitam eventos novos e o fluxo de hotfix; efeitos externos não são repetidos por uma consulta. |
| Uma tecnologia garante centenas de milhares de operações sem gargalo | Não adotada sem benchmark do ambiente e da carga. |

### 3.4 Relação com as camadas do Fable

A camada 1 de F03 é a base de uma otimização conservadora: reutilizar estado já reconstruído. A camada 2 corresponde ao uso operacional de modelos de leitura, mas depende de um modelo de confiança. A camada 3 trata crescimento do histórico e compatibilidade. A camada 4 é o snapshot operacional descrito em F02.

Este documento acrescenta: agregados de tentativas; custo de muitas tarefas elegíveis; consistência entre gerações de projeções; contexto externo; caminho autenticado; idempotência de consumidores; rastreabilidade de versão; cenários de falha e um benchmark que mede operações realmente aceitas.

## 4. Arquitetura atual e caminhos de execução

### 4.1 Componentes observados

| Componente | Responsabilidade atual | Fonte local |
|---|---|---|
| CLI | Interpreta comandos e identifica o runner | [[cli.py\|cli.py]] |
| Serviço | Coordena operações e verificação | [[service_core.py\|service_core.py]] |
| Submissão | Valida envelope, prepara eventos e efeitos | [[submission.py\|submission.py]] |
| Store | Lê, valida, bloqueia e acrescenta eventos | [[store.py\|store.py]] |
| Projetor | Reproduz eventos e forma modelos derivados | [[projector.py\|projector.py]] |
| Queries | Consulta tarefas e atividade pelo histórico | [[queries.py\|queries.py]] |
| Administração de tarefas | State, contexto e atalhos de transição | [[task_admin.py\|task_admin.py]] |
| Gates executáveis | Vinculam complete a resultados e candidatos | [[verification_gate.py\|verification_gate.py]], [[verification_candidate.py\|verification_candidate.py]] |
| Identidade e trust | Validam histórico autenticado e pin externo | [[identity_history.py\|identity_history.py]], [[trust_root.py\|trust_root.py]] |
| Snapshot | Produz artefatos históricos e compactados | [[snapshot.py\|snapshot.py]] |

### 4.2 Consulta comum

O fluxo de `task list` é: validar filtros; executar `parse_event_store`; materializar roadmap; combinar tarefas planejadas de plugins; calcular fingerprint; ordenar e filtrar; retornar página e cursor. A paginação limita a saída, mas não evita reconstruir e examinar o conjunto anterior.

`activity list` não executa replay, mas decodifica o histórico completo antes de aplicar `after_seq`, filtros e limite. `state` reconstrói um estado interno, e `dispatch-context` materializa projeções e combina referências e arquivos externos de contrato e capacidades. Pontos observados: `queries.py:49–59`, `queries.py:116–126`, `task_admin.py:152–193` no baseline.

### 4.3 Submissão comum

`submit` lê eventos e reconstrói estado; obtém a tarefa; valida contrato, runner, evidências, arquivos e autorização; aplica candidatos sobre o estado local; prepara eventos de verificação; chama o append transacional. O caminho real também pode produzir rejeições, hotfix ou resolução de issue.

No caminho normal, `append_transactional` adquire o lock, relê eventos, reproduz estado e confere precondições; chama o construtor do lote; valida o histórico final; aplica o lote ao estado do lock; acrescenta e sincroniza o log; confere a escrita; salva projeções; executa o efeito posterior; avança checkpoint externo quando aplicável. Pontos: `submission.py:129–265`, `store.py:583–654`.

A releitura sob lock é uma fronteira de consistência. Ela não é equivalente a um replay redundante feito duas vezes sobre a mesma lista imutável.

### 4.4 Projeções e verificação

`project` reconstrói e salva roadmap, issues, lessons e perfil. `verify` reconstrói o estado e compara os conteúdos armazenados, incluindo o perfil. As três projeções principais são comparadas por conteúdo normalizado, e não apenas por um campo de hash declarado. Pontos: `service_core.py:202–283` e [[projection_check.py|projection_check.py]].

O hash principal do roadmap cobre schema_version, project, tasks e indexes. Ele não é uma assinatura de todo o workspace nem substitui hashes das demais projeções, validação de identidade ou proveniência de artefatos. Ponto: `projector.py:75–82`.

### 4.5 Snapshots atuais

`create_snapshot` materializa um prefixo e grava roadmap, issues e lessons. `compact_event_store` produz arquivos auxiliares e mantém o log vivo. `replay_compacted` lê archive e tail, concatena os eventos e executa materialização completa; não restaura o estado interno do snapshot. Pontos: `snapshot.py:54–93`, `snapshot.py:96–139`, `snapshot.py:144–160`.

## 5. Diagnóstico de custo e limitações atuais

### 5.1 O que já foi resolvido

HIST: a auditoria registrou, com 50 mil eventos, cerca de 22 s para verify e 75 s para claim. O CHANGELOG b26 registra aproximadamente 2 s e 3 s após indexação de tarefas e eliminação de materializações repetidas em caminhos relevantes. A versão b27 acrescenta orientação operacional no help; não é evidência de outra transformação no algoritmo de replay.

OBS: o projetor possui índice de tarefas e aplicação incremental dentro de uma operação. Isso remove o problema específico identificado, mas não prova custo linear de toda combinação de recursos, especialmente do histórico autenticado e de muitas tarefas elegíveis.

### 5.2 Contagem estática de parsers e replays

R significa chamada a `parse_event_store`. P significa reconstrução completa por `replay_state`, direta ou via `materialize`. A tabela considera execução aceita, sem retry, sem admissão de tarefa planejada e sem caminhos adicionais de hotfix.

| Operação | R | P | Condição |
|---|---:|---:|---|
| state | 1 | 1 | Tarefa já admitida. |
| dispatch-context | 1 | 1 | Inclui trabalho externo adicional. |
| activity list | 1 | 0 | Mesmo pedindo só a cauda. |
| task list | 1 | 1 | Inclui fingerprint de todo o conjunto. |
| verify | 1 | 1 | Pode haver reconstruções adicionais no trust/checkpoint. |
| eligible | 1 | 1 | Mais varreduras por tarefa e agrupamento de conflitos. |
| claim / submit de claim | 2 | 2 | Sem admissão de plugin. |
| review pela CLI | 3 | 3 | Consulta inicial da tarefa e submissão. |
| complete sem checks executáveis | 3 | 5 ou 6 | O sexto replay ocorre com file_updates efetivos. |
| complete com checks executáveis | 3 | 8 ou 9 | Acrescenta reconstruções para validar a evidência e preparar o candidato. |
| task create | 2 | 4 | Caminho real normal, sem dry-run. |

A contagem de complete com checks inclui: consulta inicial; replay da submissão; busca da tarefa no gate inicial; preparação do candidato inicial; replay transacional; busca da tarefa no gate sob lock; nova validação de evidência; nova preparação do candidato; e, havendo arquivos, revalidação de limites. Ver `verification_gate.py:24,94,98`, `verification_candidate.py:62` e [[limit_revalidation.py|limit_revalidation.py]]:19.

Essas contagens não são instrumentação executada. Identidade e trust podem acrescentar reconstruções e varreduras, e retries mudam o total. “Submit faz dois replays” só descreve alguns envelopes.

### 5.3 Leituras físicas além de R

`_verify_appended_lines` lê o arquivo inteiro e compara as últimas linhas. O append também faz `read_bytes` para detectar ausência de newline final. Assim, duas chamadas ao parser não significam duas leituras físicas totais. Pontos: `store.py:478–488`, `store.py:631–640`.

O cache de digest do parser é por processo e evita parte das validações quando o conteúdo é igual, mas ainda relê e decodifica o histórico. A validação dependente de arquivos externos permanece ativa. Pontos: `store.py:225–270`.

### 5.4 Elegibilidade pode continuar superlinear

Para K tarefas candidatas e E eventos, as varreduras de rejeições podem produzir custo O(K × E). O agrupamento de tarefas também compara conjuntos de arquivos; ele deve ser medido à parte. Melhorar apenas o replay não elimina esses termos. Fontes: `execution.py:103–115`, [[runtime_policy.py|runtime_policy.py]]:100–146, [[seeds.py|seeds.py]]:356–407.

### 5.5 Volume observado do histórico

OBS: antes das transições desta tarefa documental, o histórico tinha 2.005 eventos e 1.261.266 bytes. Foram contados 617 verify.start e 617 verify.ok: 1.234 eventos, equivalentes a 61,55% do total. A remoção hipotética desse par corresponderia a 2,60 vezes menos eventos nessa composição. Não é autorização de remoção nem previsão equivalente de redução de bytes ou latência.

### 5.6 Modelo de custo para orientar medições

Uma aproximação útil é:

```text
T_comando = T_inicio_python + T_configuracao
          + n_parse * T_parse(E, bytes, trust)
          + n_replay * T_replay(E, tarefas, ações)
          + T_agregacoes(E, K) + T_hashes(tarefas, bytes)
          + T_serializacao(projecoes) + T_io + T_lock + T_efeitos
```

A fórmula não é um modelo calibrado. Ela impede atribuir toda a latência ao replay e ajuda a medir o efeito de cada fase. Memória inclui strings do log, linhas, objetos decodificados, estados, cópias e candidatos; não deve ser estimada simplesmente multiplicando o número de leituras por um pico isolado.

## 6. Objetivos e invariantes da evolução

### 6.1 Objetivos técnicos

PROP: reduzir reconstruções do mesmo prefixo; evitar varredura do histórico por tarefa candidata; tornar explícita a origem e a atualidade das consultas; permitir recuperação determinística de derivados; preparar retomada por snapshot; manter comportamento legado como referência de equivalência.

A definição de sucesso inclui resultados corretos e rejeições equivalentes. Uma otimização que aceita uma entrega antes rejeitada, omite lesson ativa ou usa uma autorização obsoleta não atende ao objetivo, mesmo que a latência diminua.

### 6.2 Regras de preservação

| ID | Invariante | Verificação exigida |
|---|---|---|
| RN-01 | Apenas o Orchestrator escreve eventos e aplica efeitos finais | Interfaces, testes de submissão e inspeção dos caminhos de escrita. |
| RN-02 | O histórico preserva ordenação, IDs e diagnósticos de corrupção | Comparação de códigos e sequência nos testes. |
| RN-03 | Claim e complete permanecem ações separadas | Rejeição de envelopes colapsados. |
| RN-04 | Quem reivindica é quem completa, conforme identidade aplicável | Casos de actor, alias e principal divergentes. |
| RN-05 | Done é terminal | Correção apenas pelo fluxo autorizado de issue/hotfix. |
| RN-06 | Arquivos só acompanham complete e respeitam boundaries e limites | Casos de symlink, escape, atualização concorrente e recursos. |
| RN-07 | Uma consulta não reexecuta efeitos de eventos históricos | Ausência de subprocessos de negócio, escritas de arquivos e transições. |
| RN-08 | Um derivado não se torna fonte canônica por conveniência | Reconstrução e comparação pelo histórico. |
| RN-09 | Confiança externa é reavaliada conforme sua política | Alteração de pin/âncora sem alterar o log não pode passar despercebida. |
| RN-10 | Estado e hash usados no commit correspondem ao prefixo do lock | Cenários de concorrência e retry. |
| RN-11 | Caches ausentes ou incompatíveis não impedem recuperação legítima | Caminho completo e mensagens determinísticas. |
| RN-12 | Atualidade e integridade são propriedades distintas | Respostas e documentação não usam uma como substituta da outra. |
| RN-13 | Templates distribuídos não sobrescrevem contratos ativos automaticamente | Migração explícita e teste de workspaces antigos. |
| RN-14 | Ganhos de desempenho só são anunciados depois de medidos | Resultado inclui ambiente, carga e saída funcional. |

### 6.3 Restrições operacionais

Não remover lock manualmente; não contornar STORE_LOCK_TIMEOUT, JSONL_INVALID, EVENT_SEQ_* ou APPEND_VERIFY_FAILED; não editar activity ou projeções por fora do runtime. Uma falha num cache derivado pode admitir fallback; uma falha no histórico canônico ou na confiança externa exige interrupção da operação afetada. A distinção deve aparecer nos tipos de erro, não ficar dependente de interpretação do agente.

## 7. Arquitetura proposta e responsabilidades

### 7.1 Organização lógica

PROP: manter execução local e organizar cinco responsabilidades com interfaces explícitas:

```text
Consulta -> Leitor de modelos -> validação da geração e da confiança
                            -> dados derivados + metadados de atualidade
                            -> caminho completo quando permitido/necessário

Comando -> preparação -> lock -> estado válido do prefixo
                            -> autorização e regras -> lote de eventos
                            -> append durável -> projeções -> efeitos

Snapshot operacional -> restauração validada -> aplicação da cauda
Auditoria integral   -> parser completo -> replay completo -> comparação
```

O diagrama é conceitual. Não define novos serviços, processos ou comandos existentes. A responsabilidade do Orchestrator continua abrangendo escrita canônica e efeitos; componentes auxiliares de consulta não recebem autoridade para submeter eventos.

### 7.2 Contratos internos sugeridos

| Interface proposta | Entrada | Saída | Proibição |
|---|---|---|---|
| Leitor de prefixo | Root e requisito de confiança | Eventos ou estado, sequência e identidade do prefixo | Não decidir autorização apenas por cache não confiável. |
| Contexto de replay | Prefixo consistente | Estado e agregados derivados | Não expor referências mutáveis a chamadores arbitrários. |
| Preparador de comando | Comando, tarefa e contexto | Candidato normalizado e precondições | Não aplicar efeitos finais. |
| Leitor de consulta | Filtros e exigência de atualidade | Página e proveniência | Não atualizar event store por consultar. |
| Publicador de geração | Views de um mesmo estado | Geração completa identificada | Não misturar versões de projeções. |
| Gerenciador de checkpoint | Estado e identidade do prefixo | Snapshot validado ou rejeição motivada | Não silenciar corrupção canônica. |

Os nomes são descritivos; não se propõe criar uma classe para cada linha obrigatoriamente. O objetivo é reduzir dependências implícitas e passar o estado que já existe ao componente que precisa dele.

### 7.3 Perfis de garantia

PROP: documentar separadamente três perfis, sem afirmar que já existem na CLI:

1. **Integral:** valida o histórico e reconstrói o estado como referência independente. É o comportamento a preservar em verify e em caminhos cuja garantia ainda dependa disso.
2. **Derivado com conferência integral dos bytes:** confere o vínculo de um derivado com o log inteiro, reduzindo parsing/replay quando as condições são satisfeitas. Continua O(bytes do log).
3. **Incremental sob confiança definida:** restaura um estado cuja origem está protegida e valida a cauda e os insumos externos. Pode evitar revisitar o prefixo, mas exige um modelo de confiança aprovado.

Um quarto uso, visualização de uma geração histórica explicitamente indicada, pode aceitar atraso. Ele não é substituto de estado atual para autorizar comandos.

### 7.4 Arquivos sugeridos

A implementação poderá introduzir módulos pequenos para contexto de replay, agregados de tentativas, manifesto de projeções e checkpoint. A escolha de nomes deve acompanhar as responsabilidades reais. O store deve fornecer I/O e fronteira transacional; política, autorização e regra de domínio devem manter APIs explícitas. A separação pode ser gradual, sem reescrever o runtime inteiro.

## 8. Reutilização de estado dentro do comando

### 8.1 Oportunidade e ordem de execução

OBS: já existem replay_state, apply_events, state_tasks e projection_summary. PROP: reaproveitá-los antes de adicionar persistência de cache. Essa etapa oferece benefício com menor mudança de confiança porque trabalha com um prefixo já carregado no mesmo processo.

Primeiro instrumentar reconstruções; depois passar a tarefa já localizada a validate_evidence e prepare_candidate; em seguida passar o estado sob lock aos validadores que hoje materializam novamente a mesma lista. Fontes: [[submission.py|submission]], [[verification_gate.py|gates]], [[verification_candidate.py|candidato]], [[service_core.py|serviço]] e [[limit_revalidation.py|limites]].

### 8.2 Contexto de prefixo

Um contexto proposto deve conter sequência final, identidade do prefixo, estado interno, mapa de tarefas e agregados necessários. Ele não deve permitir combinar uma tarefa do prefixo A com eventos do prefixo B.

```python
# Pseudocódigo de desenho; não é uma API existente.
context = rebuild_prefix(events)
task = context.require_task(task_id)
validate_evidence(root, context, actor, candidate, task=task)
```

A otimização não consiste apenas em acrescentar `task=None` a uma função. O contrato precisa garantir a origem da tarefa e impedir mutação acidental. Se o chamador não possui o contexto correspondente, o caminho completo permanece disponível.

### 8.3 Complete e review

No complete, issue_id e fixes podem ser resolvidos durante a submissão, a partir da tarefa já obtida, eliminando a consulta inicial exclusiva para essa finalidade. O comportamento de argumentos explícitos, valores herdados, erros de tarefa ausente e notificações deve permanecer equivalente.

No review, a consulta inicial serve à condição de notificação. Ela pode ser substituída por informação retornada da submissão aceita, preservando dry-run, request_changes, tarefa resultante e notificações. Não basta testar `status=accepted` sem verificar o resultado final esperado.

### 8.4 Validação de lotes

`validate_pending` pode restaurar um estado do prefixo uma vez e avançá-lo evento a evento. Para cada complete, a tarefa deve ser avaliada no estado imediatamente anterior àquele evento, considerando alterações anteriores do mesmo lote. Resultados de verificações executáveis continuam vinculados ao candidato, configuração, ciclo, entradas e actor.

O estado avançado deve ser descartável. Se o lote for rejeitado após uma aplicação parcial, ele não pode contaminar uma tentativa posterior ou o estado já validado do store. A necessidade de cópia deve ser determinada pelo contrato de propriedade do objeto, e não removida indiscriminadamente.

### 8.5 Revalidação sob lock

É possível reutilizar o estado que append_transactional acabou de reconstruir. Não é correto reutilizar sem conferência o estado construído antes do lock. Limites, orçamento de tentativas, identidade e evidência devem continuar sendo avaliados no prefixo efetivamente usado no commit.

PROP: o construtor transacional receber um contexto de prefixo somente para a duração da transação; o runtime continua responsável por rejeitar estado obsoleto e reconstruir em retry. Isso pode exigir ajuste de assinaturas internas e testes de todos os chamadores.

### 8.6 Critérios de aceite desta etapa

Contagens de replay devem cair nos caminhos escolhidos; outputs e projeções devem ser equivalentes; rejeições devem manter código e ausência de efeitos; a validação sob lock deve permanecer; lotes com múltiplos completes e modificações de entradas devem continuar sendo rejeitados quando necessário. A contagem-alvo só deve ser fixada após definir quais funções recebem contexto e como ficam os caminhos autenticados.

## 9. Agregados incrementais para elegibilidade

### 9.1 Estado mínimo sugerido

PROP: durante uma única passagem, manter por tarefa: número de rejeições penalizantes; horário da última rejeição; última liberação; runner da reivindicação e da entrega do ciclo atual quando necessário; referências de dependências; status e arquivos previstos. O relógio atual não deve ser gravado como verdade permanente: cooldown e TTL são calculados usando timestamps e o instante da consulta.

Um mapa derivado de tentativas precisa reproduzir exatamente a regra atual de [[runtime_policy.py|runtime_policy.py]], inclusive a exceção PRIOR_STATUS_MISMATCH e o reset por task.release. Não reinterpretar agora o significado de penalizes_counter apenas por existir texto histórico sobre esse campo.

### 9.2 Transições do agregado de tentativas

| Evento | Mudança proposta no agregado |
|---|---|
| task.create / hotfix.create | Inicializar o estado da tarefa quando aplicável. |
| output.rejected da tarefa | Acrescentar à contagem conforme a regra atual; atualizar última rejeição conforme semântica vigente. |
| task.release da tarefa | Zerar contagem e última rejeição como no algoritmo atual. |
| claim | Registrar início do ciclo e identificação necessária. |
| complete | Registrar entrega do ciclo sem apagar histórico de tentativas arbitrariamente. |
| review request_changes | Atualizar ciclo conforme regra de evidência e transição existente. |
| Eventos sem relação | Não modificar o agregado daquela tarefa. |

### 9.3 Consulta de elegibilidade

A consulta deve: selecionar tarefas todo não superseded; verificar dependências done; consultar o agregado de tentativas; calcular cooldown; produzir stale_claims com o instante da consulta; montar grupos de compatibilidade de escrita. A redução pretendida é retirar o termo O(K × E) das rejeições, preservando os demais custos explícitos.

A primeira entrega pode reconstruir esses agregados a cada comando numa única passagem. Persisti-los fica para uma etapa posterior. Isso facilita provar equivalência antes de introduzir cache entre processos.

### 9.4 Dependências e conflitos

Contadores de dependências pendentes podem acelerar seleção, mas exigem considerar task.amend, supersedes e tarefas planejadas. Um índice reverso de dependentes deve ser atualizado quando vínculos mudarem; snapshots devem preservá-lo ou reconstruí-lo deterministicamente.

O agrupamento de arquivos possui semântica de padrões de escrita, não simples igualdade de nomes. Índices de conflito devem respeitar glob, diretórios e normalização existentes. Antes de substituir o algoritmo, medir seu peso real com muitas tarefas elegíveis.

### 9.5 Critérios de aceite

Comparar o algoritmo antigo e o agregado em históricos com rejeições intercaladas, releases, cooldown expirado/não expirado, timestamps inválidos, tarefas com dependências e tarefas superseded. Medir 1, 100 e 1.000 candidatas no mesmo E. O crescimento das varreduras de rejeição deve deixar de acompanhar E × K.

## 10. Modelos de consulta e política de confiança

### 10.1 Modelos especializados

PROP: começar com dados que removem trabalho repetido identificável:

| Consulta | Modelo útil | Trabalho que permanece |
|---|---|---|
| state | Mapa de tarefa por ID e resumo do prefixo | Overlays de tarefas planejadas e metadados exigidos. |
| task list | Índices por status, tipo e responsável | Filtros, ordenação, cursores e atualização de plugins. |
| eligible | Tarefas, dependências e tentativas | Cálculo temporal e agrupamento de conflitos. |
| dispatch-context | Estado e projeções consistentes | Contratos, schema, lessons filtradas, perfil e capacidades. |
| activity list | Índice de offsets e metadados | Leitura das entradas selecionadas e aplicação de filtros. |

A projeção pode começar em JSON. Um mapa serializado ainda precisa ser carregado e decodificado: achar uma tarefa nele não transforma todo o comando em O(1). Índices persistentes ou armazenamento diferente são decisões posteriores baseadas em medição.

### 10.2 Manifesto de conferência

O head de F03 pode evoluir para um manifesto versionado. Campos mínimos propostos: versão do formato; identificador da geração; identidade do workspace; tamanho, sequência e hash exato do log; versão/fingerprint do projetor; lista fechada de projeções com hashes; presença ou ausência explícita do perfil; perfil de confiança usado; referência à geração anterior quando necessária à recuperação.

Um manifesto deve ser validado por esquema antes de usar nomes de arquivo. Rejeitar caminhos absolutos, traversal, chaves extras indevidas, listas incompletas e hashes malformados. O próprio arquivo não é autoridade criptográfica só por conter hashes.

### 10.3 Hash de bytes e hash semântico

O hash dos bytes detecta diferenças do arquivo observado; o hash da projeção representa os campos definidos pelo projetor; o hash de histórico do trust usa sua representação canônica. Eles não são intercambiáveis. Um manifesto precisa dizer qual algoritmo e qual representação cada campo usa.

Não substituir o digest do parser baseado no texto normalizado por um hash de bytes sem avaliar CRLF, linhas em branco e compatibilidade. Um cache novo pode ser mais estrito na invalidação, mas não deve rejeitar um histórico aceito pelo parser de referência apenas por diferenças de representação.

### 10.4 Três cenários de adulteração

1. **Só a projeção muda:** o hash registrado no manifesto deve divergir; o caminho integral identifica a divergência com o replay.
2. **O log muda e o manifesto antigo permanece:** tamanho ou hash integral deve divergir, inclusive para alteração de mesmo tamanho.
3. **Log, projeções e manifesto são substituídos coerentemente:** hashes locais podem concordar. Sem autoridade externa que proteja a origem, verify pode aceitar uma história alternativa estruturalmente válida. Não prometer detecção universal.

O terceiro caso é a razão para manter identidade, pin, checkpoints e modelo de ameaça explícitos. “Derivado conferido” descreve uma checagem, não uma prova de autenticidade de tudo que a antecedeu.

### 10.5 Invalidação por dependências externas

Mesmo com log idêntico, podem mudar: contratos ativos, schema de envelope, política, swarm, plugins planejados, perfil registrado por outras fontes previstas no código, capacidades do runner, âncora local e trust externo. Nem todos esses itens precisam entrar no cache do estado base: alguns podem ser carregados novamente e combinados depois. A fronteira precisa ser explícita.

Para dispatch-context, preservar a filtragem de lessons e issues por tarefa e ação. Não servir um contexto integralmente antigo só porque roadmap não mudou. Para tarefas planejadas, manter a composição com plugins e invalidar cursores quando o universo consultado mudar.

### 10.6 Atualidade e proveniência da resposta

Campos conceituais sugeridos: sequência da geração; sequência observada no store; versão do projetor; modo de leitura; verificações realizadas; motivo do fallback; indicação de atraso quando permitida. Qualquer mudança no JSON público deve respeitar compatibilidade, documentação e testes de consumidores.

Um parâmetro futuro de sequência mínima permitiria que o agente pedisse uma geração pelo menos tão recente quanto a submissão anterior. Se a exigência não for atendida, o runtime deve reconstruir ou falhar de modo explícito. Os nomes de flags e campos não são definidos nesta versão documental.

### 10.7 Falhas e fallback

Cache ausente, formato desconhecido ou digest divergente podem levar ao caminho completo sem criar arquivos numa consulta. Corrupção canônica, erro de identidade e rollback externo não podem ser reclassificados como simples cache miss. O fallback não deve esconder incidente nem sobrescrever a evidência automaticamente.

### 10.8 Condição para uso inicial

PROP: inicialmente, permitir o atalho apenas para a classe de histórico cuja equivalência e confiança tenham sido demonstradas. Identidade ou pin ativos devem permanecer no caminho completo até haver restauração autenticada com cobertura adequada. Isso é uma limitação da primeira implementação, não autorização para desabilitar proteções de um workspace.

## 11. Publicação consistente de projeções

### 11.1 Limite da situação atual

OBS: o runtime salva múltiplas projeções sequencialmente após o append. Há proteção de substituição individual, mas isso não constitui uma transação atômica entre todos os arquivos. Uma consulta que passar a ler diretamente esses arquivos precisa reconhecer se pertencem ao mesmo prefixo. Ver [[store.py|store.py]]:642–645 e [[projection_check.py|comparação de projeções]].

### 11.2 Publicação por geração

PROP: produzir os arquivos de uma geração em caminhos novos, validar hashes e esquema, sincronizar os arquivos e publicar por último um manifesto pequeno que aponta para essa geração. O leitor usa apenas os caminhos da geração escolhida; não combina arquivos atuais de uma geração com arquivos antigos de outra.

```text
Derivados propostos, não presentes como contrato atual:
  gerações/<id>/roadmap.json
  gerações/<id>/issues.json
  gerações/<id>/lessons.json
  gerações/<id>/project_profile.json  [ou ausência explícita]
  manifesto-atual.json
```

O layout final deve ser decidido sem alterar silenciosamente os caminhos públicos legados. Uma fase de compatibilidade pode continuar produzindo os arquivos atuais enquanto leitores novos usam gerações. A geração nova só é visível depois de completa; a anterior permanece disponível até não haver leitores dependentes.

### 11.3 Ordem e durabilidade

A ordem proposta é: concluir validação; acrescentar o lote ao log e sincronizar; preparar/publicar a geração correspondente; finalizar efeitos conforme o protocolo; atualizar marcos externos no ponto coerente com as garantias existentes. Essa ordem precisa ser examinada junto ao recovery de efeitos, pois “projeção publicada” e “todos os efeitos aplicados” são afirmações diferentes.

Atomicidade de rename de um arquivo não equivale a durabilidade de todo o diretório em qualquer plataforma. A implementação deve usar as primitivas já adotadas pelo projeto e validar a sincronização necessária nos sistemas suportados. Não anunciar garantia de queda de energia apenas porque há os.replace ou fsync em um ponto.

### 11.4 Leitura concorrente

Um leitor deve obter um manifesto consistente, abrir os arquivos daquela geração e verificar seus vínculos. Se um escritor publicar uma geração nova depois disso, a leitura da geração anterior pode ser válida como fotografia de um instante, conforme a garantia da consulta. Se o comando exige a sequência mais recente, deve conferir a atualidade ou usar a fronteira de sincronização apropriada.

A conferência do log para um cache deve observar um prefixo estável. Ler tamanho, hash e arquivos em instantes diferentes sem proteção pode combinar versões. Testes precisam forçar append concorrente, troca de manifesto, remoção de geração e falhas entre passos.

### 11.5 Recuperação

| Ponto da falha | Estado esperado | Reação proposta |
|---|---|---|
| Antes do append | Nenhum novo evento persistido | Descartar staging pelo mecanismo existente. |
| Após append, antes de projeções completas | Log à frente dos derivados | Caminho integral e rebuild autorizado. |
| Durante preparação de uma geração | Geração incompleta não publicada | Ignorar como ativa; limpar por operação de manutenção. |
| Depois de publicar manifesto | Geração completa identificável | Servir a geração e conferir os demais estados do commit. |
| Manifesto inválido ou ausente | Derivado indisponível | Ler pelo caminho completo; não criar arquivos por consulta. |
| Efeito de arquivo pendente | Histórico registra intenção e artefatos | Usar recuperação de efeitos, sem afirmar sucesso externo inexistente. |

## 12. Snapshots operacionais e replay da cauda

### 12.1 Diferença entre snapshot e read model

Uma projeção responde a uma necessidade de leitura. Um snapshot operacional deve permitir continuar a máquina de estados e todas as validações afetadas. O roadmap isolado não contém necessariamente registro de identidade, nonces, configuração de checks, rejeições, cadeia e demais informações derivadas de eventos.

PROP: versionar separadamente formato do snapshot, semântica do projetor e algoritmos dos agregados. A restauração deve produzir um contexto equivalente ao obtido pelo replay completo do mesmo prefixo.

### 12.2 Conteúdo do snapshot

| Grupo | Conteúdo a estudar | Razão |
|---|---|---|
| Identificação | Workspace, geração, versão e sequência final | Impedir uso cruzado e mistura de formatos. |
| Posição | Offset exato em bytes e limite de registro completo | Ler a cauda sem procurar desde o início. |
| Prefixo | Identidade/digest definido do prefixo e estado da cadeia | Vincular o estado ao histórico correto. |
| Domínio | Tarefas, issues, lessons, metadados e perfil | Continuar a projeção sem perda. |
| Índices | IDs de tarefa, dependências e consultas úteis | Evitar reconstrução indevida de estruturas. |
| Tentativas | Contagem e timestamps por tarefa | Preservar bloqueio, cooldown e releases. |
| Execução | Configuração e referências de verificações | Preservar ligação entre candidato e evidência. |
| Identidade | Registro, aliases, principais, nonces e vínculos necessários | Continuar autenticação e separação de revisão. |
| Efeitos | Referências necessárias a pendências e recovery | Não perder entregas ainda não aplicadas. |
| Compatibilidade | Schema dos eventos e versão de cada agregado | Detectar snapshot obsoleto. |
| Integridade | Hash do artefato e vínculo protegido quando exigido | Detectar corrupção e, com autoridade adequada, substituição. |

A tabela é um inventário de necessidades, não um schema fechado. A análise de todos os consumidores de eventos deve demonstrar quais campos são necessários, suficientes ou reconstruíveis sem custo proibitivo.

### 12.3 Criação

Escolher um prefixo consistente; reconstruir ou obter um estado já validado; serializar de forma determinística; registrar sequência e offset; calcular o hash do artefato; executar validação de restauração; publicar o snapshot por operação do Orchestrator. A frequência deve considerar eventos desde o último snapshot, bytes de cauda, tempo de replay e custo do próprio snapshot.

Não escolher “a cada 100 eventos” como requisito sem medir. Um histórico de poucos eventos com payloads grandes difere de milhares de pequenos eventos administrativos.

### 12.4 Restauração e aplicação da cauda

```python
# Pseudocódigo de proposta; omite APIs de I/O e erros concretos.
checkpoint = load_checkpoint_metadata(root)
assert_supported_format(checkpoint)
assert_workspace_binding(checkpoint)
assert_checkpoint_trust(root, checkpoint)
state = restore_state(checkpoint)
validate_state_invariants(state)
for event in read_complete_tail(checkpoint.byte_offset):
    validate_next_event(event, state)
    authenticate_next_event(root, event, state)
    apply_event_and_aggregates(state, event)
return state
```

O loop precisa preservar os diagnósticos e a normalização de eventos legados. O offset deve apontar após um registro completo. Uma cauda parcialmente escrita não autoriza reparo automático; aplica-se a regra atual de corrupção e a operação explícita de repair quando permitida.

### 12.5 Confiança no prefixo

Há três possibilidades distintas:

- Recalcular o hash de todo o prefixo em cada restauração: economiza parsing e replay, mas preserva custo linear de leitura.
- Usar um checkpoint protegido por autoridade externa e pressupostos de armazenamento definidos: pode evitar a leitura integral, mas muda o argumento de confiança e exige uma decisão formal.
- Usar só tamanho/mtime e um arquivo local editável: detecta alguns acidentes e não equivale às garantias integrais atuais.

Uma cadeia de hashes também não revela alterações em bytes que não são lidos sem um mecanismo que proteja a referência confiável e a relação com o armazenamento. A origem do snapshot e a integridade do prefixo precisam ser demonstradas; “tem SHA-256” não é uma demonstração suficiente.

### 12.6 Identidade e replay autenticado

O snapshot autenticado é uma etapa separada. OBS: o validador cronológico percorre prefixos e chama funções de registro e autorização. Portanto, o desempenho do histórico puramente legado não prova o desempenho do histórico autenticado. Ver [[identity_history.py|identity_history.py]]:77 em diante e [[trust_root.py|trust_root.py]].

A restauração precisará preservar prevenção de replay de credenciais, nonces, separação de principais, escopos e checkpoint anti-rollback. Dados do pin e da âncora externos devem ser reavaliados; não podem ser congelados como verdade permanente dentro de um snapshot controlado pelo projeto.

### 12.7 Equivalência exigida

Para um histórico H e um corte N, deve valer: restaurar snapshot de H até N e aplicar H após N produz as mesmas projeções e decisões que replay integral de H. A igualdade abrange comportamento de comandos posteriores, e não somente o hash do roadmap.

Validar vários cortes, inclusive imediatamente antes e depois de claim, complete, review, release, mutation de lessons, mudanças de limites, configuração executável e ativação de identidade. Eventos desconhecidos para o formato do snapshot devem provocar fallback ou rejeição compatível, nunca ser ignorados.

### 12.8 Custo remanescente

Snapshots não eliminam o tamanho do estado atual, a serialização das projeções, a checagem de conteúdo de arquivos candidatos, o I/O dos efeitos ou a espera de lock. Mesmo com cauda pequena, um workspace com centenas de milhares de tarefas pode exigir modelos de leitura mais seletivos e outra estratégia para publicar o roadmap legado.

## 13. Identidade, confiança externa e concorrência

### 13.1 Estado de domínio não substitui autorização

Uma tarefa elegível no read model pode deixar de ser elegível antes de claim. A decisão final deve verificar o estado coerente sob lock. O contexto enviado ao agente é uma fotografia; não é uma autorização irrevogável para modificar o workspace.

O mesmo princípio vale para complete: dono da tarefa, principal, limites, configuração de checks e entradas verificadas podem precisar de revalidação. Para review, manter qa_role, política de separação de runner e identidade quando ativadas. Fontes: [[validator.py|validator]], [[identity.py|identity]], [[runtime_policy.py|política]] e [[verification_gate.py|evidências]].

### 13.2 Checkpoint externo

OBS: o trust compara bootstrap, pin, âncora, checkpoint e hash de histórico, e rejeita regressão. verify também pode avançar o checkpoint externo por catch_up_checkpoint. Assim, “consulta” e “nenhuma escrita em lugar algum” não são sinônimos para todos os comandos atuais. Esse comportamento precisa ser preservado ou alterado explicitamente, com documentação; não escondido no cache. Fonte: `trust_root.py:132–249`.

PROP: distinguir nas APIs a validação de confiança e o avanço do checkpoint. Um leitor puramente informativo não deve adquirir autoridade de atualizar confiança por efeito incidental de carregar uma projeção. Qualquer separação dessa responsabilidade exige compatibilidade com as garantias atuais de recovery e anti-rollback.

### 13.3 Retries

Uma submissão obsoleta pode ser refeita sobre prefixo novo pelo mecanismo atual. O contexto antigo, os hashes e as verificações dependentes do prefixo devem ser invalidados ou refeitos conforme a regra vigente. Já existe refresh de hashes de verificação em retry; a otimização precisa integrar-se a esse fluxo. Fonte: [[orchestrator_commit.py|orchestrator_commit.py]]:107 e `service_core.py:321–350`.

Medir separadamente o caminho sem contenção e o caminho com conflitos. Um teste que conta dois replays em execução isolada não estabelece o máximo sob concorrência.

### 13.4 Redução de leituras após append

PROP: substituir a releitura integral de `_verify_appended_lines` por conferência dos bytes efetivamente acrescentados, usando o offset anterior conhecido sob lock. A implementação deve verificar comprimento esperado, separador eventualmente inserido, conteúdo exato, posição e ausência de bytes inesperados no limite conferido.

Isso preserva uma verificação da escrita, mas não constitui auditoria integral do prefixo. Testar ausência de newline final, CRLF legado, linhas em branco, Unicode, append parcial e interferência detectável. Não usar a mudança para retirar o read-after-write obrigatório.

## 14. Índices de atividade e histórico por tarefa

### 14.1 Índice global por sequência

PROP: manter checkpoints esparsos que associem sequência e offset. Para `after_seq`, encontrar o checkpoint anterior, ler registros completos a partir dele e descartar até a sequência desejada. O índice deve ser vinculado à identidade do log e invalidado após truncamento, substituição ou manutenção autorizada.

OBS: o parser ignora linhas em branco. Portanto, event_seq corresponde à posição entre registros não vazios validados; ele não é necessariamente o número físico da linha. A equivalência simplificada de F03 não deve fundamentar um seek por contagem bruta de quebras de linha. Fonte: `store.py:263,283–305`.

### 14.2 Filtros e paginação

Parar após limit + 1 resultados só é correto contando registros que satisfazem os filtros. Pedir 50 eventos de uma tarefa rara pode exigir examinar muito mais que 51 eventos globais. Um índice por tarefa ou por ação pode ajudar, mas tem custo de manutenção e memória.

A resposta precisa continuar informando has_more e last_event_seq com a semântica definida. A última sequência global não deve ser confundida com a última sequência encontrada pelo filtro. A validação de after_seq negativo, limites e ações precisa permanecer equivalente.

### 14.3 Índice por tarefa

Guardar referências aos eventos de cada tarefa facilita timeline, rejeições, runners do ciclo e diagnóstico. O índice deve cobrir eventos relacionados que não possuam o mesmo formato de payload e documentar quais relações foram incluídas. Um evento global de política ou identidade pode afetar uma tarefa sem ter seu task_id.

Por isso, o índice não autoriza reconstruir uma tarefa isoladamente e concluir que todas as suas transições estão autorizadas. Dependências, políticas, lessons e identidade continuam podendo ter alcance global.

### 14.4 Streams lógicos e log canônico

PROP: tratar streams por tarefa como visão lógica do log global. Não dividir imediatamente o arquivo canônico nem introduzir múltiplos escritores. A sequência global é útil para auditoria, causalidade de mudanças e sincronização. Uma eventual mudança para stores físicos por stream exigiria outro estudo de transações e invariantes entre tarefas.

## 15. Eventos de verificação e crescimento do log

### 15.1 Diagnóstico

OBS: verify.start e verify.ok continuam sendo emitidos em diversas escritas. O projetor marca o status ao receber verify.ok, sem comparar naquele ponto o hash do payload com uma recomputação independente. Isso não deve ser confundido com o comando verify, que reconstrói e compara as projeções. Fonte: `projector.py:434–437`, `service_core.py:225–283` e FUN-04 na [[auditoria-esaa-20261110|auditoria]].

### 15.2 Opções de desenho

| Opção | Benefício | Custo ou risco |
|---|---|---|
| Manter o par | Compatibilidade e trilha existente | Crescimento e parsing adicionais. |
| Omitir o par em novas escritas por política | Reduz volume futuro | Altera status derivado, snapshots e consumidores. |
| Registrar resumo de verificação por lote | Explicita vínculo da validação | Requer semântica e versionamento do lote. |
| Registrar hash em evento do lote | Reduz eventos auxiliares | Exige regra de cálculo que evite custo quadrático. |

PROP: medir bytes, eventos e tempo antes de decidir. A retirada do par não acelera automaticamente o processamento do histórico antigo. O histórico existente deve continuar legível sem ser reescrito para eliminar eventos.

### 15.3 Evitar a volta do custo quadrático

Se cada verificação de lote durante um replay recalcular o hash completo de todas as tarefas acumuladas, o custo pode voltar a crescer de forma superlinear. Opções a estudar: validação integral independente em momentos explícitos; digest incremental com formato e propriedades próprios; checks em marcos definidos; manutenção de índices agregados. Nenhuma dessas alternativas pode substituir o hash público atual sem analisar compatibilidade.

### 15.4 Compatibilidade de política

OBS: a política atual rejeita chaves desconhecidas. Portanto, uma opção nova exige atualização do schema distribuído, carregador, documentação, templates, testes e estratégia de migração. Não acrescentar uma chave local esperando que tenha efeito. Fontes: [[runtime_policy.py|runtime_policy.py]]:53–66 e [[runtime_policy.schema.json|schema de política]].

Antes de retirar o par, resolver a dependência de compactação no último verify.ok e definir como verify_status é reconstruído. Um valor salvo só no arquivo derivado não satisfaz, por si só, a reconstrução por eventos.

## 16. Consultas temporais e evolução do projetor

### 16.1 Estado em uma sequência

PROP: oferecer uma interface de consulta histórica baseada em event_seq, com saída explicitamente identificada como histórica. Ela pode apoiar investigação de incidentes, compreensão de uma rejeição e comparação de decisões do agente com o contexto disponível naquele instante.

O estado temporal deve incluir tarefas, issues e lessons do prefixo pertinente. Contratos externos atuais não devem ser apresentados como se fossem contratos históricos se não houver evidência versionada de seu conteúdo. A resposta precisa distinguir “estado do domínio no evento N” de “reprodução de todo o ambiente operacional daquela época”.

### 16.2 Comparação de projetores

Duas versões do projetor podem produzir estados distintos sobre o mesmo histórico. Um procedimento de avaliação deve fixar bytes do histórico, versão do runtime e regras de normalização; executar versões em ambiente isolado; comparar projeções normalizadas; classificar diferenças intencionais e regressões.

Mudança de versão de pacote não deve invalidar automaticamente todo cache quando a semântica do projetor é idêntica, mas uma versão de pacote sozinha também pode ser um identificador insuficiente para builds de desenvolvimento. PROP: adotar identificador de compatibilidade do projetor, com atualização disciplinada e testes.

### 16.3 Evolução de eventos

Eventos antigos precisam continuar interpretáveis. Preferir adaptação de leitura explícita e testada a reescrever bytes do histórico. Um evento novo pode exigir novos agregados e invalidar snapshots antigos. A matriz de compatibilidade deve dizer se o runtime restaura, reconstrói integralmente ou rejeita uma versão de snapshot.

O teste deve distinguir erro de formato de snapshot de ação desconhecida no log canônico. O primeiro pode justificar fallback; o segundo segue o tratamento de integridade do parser.

### 16.4 Replay sem efeitos

Reaplicar eventos para produzir estado não executa novamente comandos de negócio. O módulo de projeção deve permanecer separado de execução de subprocessos, notificações e recuperação de efeitos. Um replay de complete não pode voltar a gravar o arquivo final apenas porque o evento foi lido.

Quando houver necessidade de corrigir uma entrega anterior, usar issue.report e hotfix com nova autorização. Uma consulta histórica ou reconstrução de cache não contorna done terminal.

## 17. Integrações e consumo confiável de eventos

### 17.1 O que aproveitar da discussão de CDC e outbox

F01 descreve a dificuldade de escrever o estado e publicar uma mensagem em sistemas distintos. No ESAA, o log durável já oferece uma sequência que pode orientar consumidores futuros. PROP: integrações derivadas consumirem eventos confirmados com checkpoint e idempotência, em vez de depender de uma publicação não durável feita depois do comando.

Essa orientação não transforma todo efeito de arquivo atual em uma outbox genérica. O protocolo existente possui staging, artefatos e recuperação, e deve ser analisado por suas próprias garantias. Fonte: [[file_effects.py|file_effects.py]], especialmente commit_staged e recover_file_effects.

### 17.2 Contrato do consumidor

Consumidor proposto precisa registrar: workspace; identificador da integração; última sequência confirmada; versão da transformação; idempotency key por evento/efeito; estado de falha. Aplicar um evento repetido deve ser seguro ou detectado antes de repetir o efeito.

O checkpoint avança depois que o destino confirma a aplicação. Uma falha entre destino e checkpoint pode causar reentrega; por isso checkpoint isolado não oferece exatamente uma execução externa. A integração precisa da idempotência adequada ao destino.

### 17.3 Autoridade e escopo

Consumidores de dashboards e relatórios podem ler o log ou modelos autorizados. Eles não recebem autoridade de escrever no event store nem de alterar entregas. Qualquer integração que envie mensagens, publique conteúdo ou execute efeitos externos requer autorização própria; o estudo não a concede.

### 17.4 Quando adicionar mensageria

Kafka, filas ou workers externos só devem entrar quando houver necessidade demonstrada de distribuição, isolamento de consumidores, retenção e vazão. Para o objetivo atual, a primeira alternativa é leitura local incremental e processamento síncrono dos derivados necessários à CLI.

## 18. Plano de benchmark e observabilidade

### 18.1 Limites do script fornecido

OBS por inspeção de [[bench_esaa.py|F04]]:

- O gerador cria ciclos sintéticos de seis eventos e deixa uma tarefa seguinte pendente. Isso representa bem um histórico de muitas tarefas concluídas, mas não uma grande fila elegível.
- O caminho medido de complete não entrega arquivos nem usa checks executáveis.
- Não há cenário de identidade ativa, trust externo, cadeia ancorada ou contenção.
- Operações com erro imprimem exit/stderr e o programa continua; um número baixo pode representar rejeição.
- O menor tempo de três repetições é apresentado, sem mediana ou dispersão.
- O RSS é o máximo acumulado dos subprocessos encerrados, não uma medição individual de cada comando; o gerador no processo pai fica de fora.
- `--version` fornece uma aproximação do custo fixo da CLI, incluindo imports e inicialização; não mede apenas o interpretador vazio.
- O script não informa explicitamente o runner real em cada subprocesso que escreve. A forma operacional deve ser ajustada antes de usá-lo como evidência governada.
- Os históricos sintéticos são montados por funções de baixo nível, como fixtures. Isso não demonstra que todas as transições foram submetidas individualmente ao protocolo.

`task list --limit` existe no baseline. O gerador é próximo do teste de aceitação do repositório, mas a equivalência de carga precisa ser registrada, e não presumida para todos os cenários.

### 18.2 Cargas propostas

| Carga | Eventos | Composição | Objetivo |
|---|---|---|---|
| B01 | 2 mil, 10 mil, 50 mil | Tarefas concluídas e uma pendente | Comparar com o baseline histórico. |
| B02 | 50 mil, 200 mil, 500 mil | Mesmo perfil de ações de B01 | Curva de escala e memória. |
| B03 | 50 mil fixos | 1, 100 e 1.000 tarefas elegíveis | Evidenciar o termo E × K. |
| B04 | 50 mil | Rejeições, releases e request_changes | Exercitar agregados de tentativas. |
| B05 | 50 mil | Complete com arquivos pequenos e maiores | Custo de efeitos e limites. |
| B06 | 50 mil | Checks executáveis e candidatos válidos | Caminho completo de evidência. |
| B07 | Escalas progressivas | Identidade, aliases, nonces e pin ativo | Custo e correção do histórico autenticado. |
| B08 | Escalas progressivas | Cadeia ancorada | Custo da validação da cadeia. |
| B09 | 50 mil ou carga real sanitizada | Escritores concorrentes em tarefas distintas | Lock, retry e correção. |
| B10 | 200 mil, corte em 190 mil | Snapshot e cauda de 10 mil | Equivalência e ganho da restauração. |
| B11 | Poucos eventos e payloads grandes | Crescimento em bytes | Separar bytes de contagem de eventos. |
| B12 | Muitos estados atuais | Grande número de tarefas, issues e lessons | Custo do estado e publicação de projeções. |

Esses tamanhos são propostas de experimento. B02 em 500 mil só deve ser executado depois de estimar memória, disco e duração a partir das escalas menores. Não executar sobre o workspace de produção do projeto.

### 18.3 Correção do harness

PROP: criar workspaces temporários isolados; fixar os contratos efetivamente usados; identificar runner; não copiar credenciais de trust; gerar identidades de teste quando necessárias; separar preparação de medição; impor timeout; falhar se o comando não produzir o estado esperado; guardar stdout/stderr completos em artefato restrito; sempre validar o estado final.

Para escrita, restaurar a mesma base antes de cada amostra. Medir claim repetidamente sobre uma tarefa já reivindicada mede rejeição, não o mesmo comando. Para consultas, usar processos novos e distinguir cache do sistema operacional de caches internos ao processo. Um teste com processos novos ainda pode encontrar páginas de arquivo aquecidas pelo sistema.

### 18.4 Métricas obrigatórias

| Métrica | Forma de coleta proposta | Interpretação |
|---|---|---|
| Tempo de parede | Relógio monotônico por processo/comando | Experiência efetiva da CLI. |
| Mediana e dispersão | Múltiplas amostras independentes | Evitar concluir pelo melhor caso. |
| p95 | Só com amostragem suficiente e método declarado | Não apresentar percentil de três pontos como estável. |
| CPU | User/system por subprocesso | Separar processamento de espera. |
| RSS máximo | Medição individual do filho | Não confundir pico acumulado com pico do comando. |
| Bytes lidos/escritos | Instrumentação definida e validada | Identificar I/O integral restante. |
| Chamadas ao parser/replay | Instrumentação dos pontos reais | Detectar regressão de reconstruções. |
| Eventos aplicados | Contagem por contexto de replay | Provar uso da cauda. |
| Hashes e serializações | Contagem e duração por artefato | Detectar recomputação repetida. |
| Lock | Espera e duração sob lock | Distinguir latência de contenção e de trabalho. |
| Fallback/retry | Motivo e contagem | Mostrar quando o caminho rápido não é usado. |
| Correção | Exit code, status e projeções comparadas | Distinguir sucesso de falha rápida. |

### 18.5 Registro reproduzível

Cada relatório deve incluir commit, versão, Python, sistema, CPU, RAM disponível, armazenamento, filesystem, configuração de trust, política, quantidade de tarefas, eventos, bytes, composição de ações, tamanho da cauda, preparação, número de amostras e limitações. Não armazenar tokens, assinaturas privadas ou credenciais em telemetria pública.

Exemplo de resultado futuro, sem valores inventados:

```json
{
  "benchmark_schema": "proposta-1",
  "baseline_commit": "commit efetivamente medido",
  "candidate_commit": "commit efetivamente medido",
  "workload": "B03",
  "event_count": 50000,
  "eligible_task_count": 1000,
  "samples": [],
  "correctness_passed": null,
  "environment": {},
  "limitations": []
}
```

### 18.6 Metas e limites de desempenho

HIST: o teste de aceitação existente exige verify e claim abaixo de 3 s no host de referência, mas é condicionado à variável ESAA_RUN_PERFORMANCE_BENCHMARK=1. Ele não estabelece um SLA universal nem mede todas as operações. Fonte: [[test_replay_performance.py|test_replay_performance.py]]:456–520.

HIP: reduzir reconstruções e parsing deve melhorar a latência; o ganho precisa ser medido por carga. Os números de F03 — leituras abaixo de 0,5 s, escritas de 2–3 s em 50 mil e 20–30 s em 500 mil — não são critérios aprovados nem resultados deste estudo.

PROP: definir metas relativas inicialmente: reduzir contagens de trabalho sem regressão funcional; registrar latência mediana e memória; estabelecer limites por host depois da linha de base. Para snapshots, medir separadamente restauração, conferência de prefixo, processamento da cauda e publicação.

## 19. Estratégia de testes e critérios de aceite

### 19.1 Princípio de verificação

O replay integral existente deve funcionar como referência independente durante a evolução. Os testes precisam comparar dados, decisões e falhas. Comparar apenas um hash calculado pelo mesmo caminho pode reproduzir o mesmo defeito em ambos os lados.

Separar testes de equivalência, integridade, concorrência, recuperação, compatibilidade e escala. Os testes de tempo devem ser complementados por contagens determinísticas de trabalho; tempo de parede sozinho é sensível ao host.

### 19.2 Matriz de testes proposta

| ID | Cenário | Resultado exigido |
|---|---|---|
| T01 | Cada corte do histórico rico | Snapshot/estado incremental igual ao replay integral. |
| T02 | Mesmo estado em duas views retornadas | Mutar uma cópia não altera a outra ou o estado interno. |
| T03 | Complete com tarefa já obtida | Evidência e rejeições iguais ao caminho antigo. |
| T04 | Complete sem arquivos | Redução de replay comprovada pelo contador. |
| T05 | Complete com arquivos | Limites e revalidação sob lock preservados. |
| T06 | Checks executáveis válidos | Candidato, ciclo e entradas continuam vinculados. |
| T07 | Entrada modificada depois da execução do check | Entrega rejeitada como obsoleta. |
| T08 | Outro complete do lote altera entrada | Lote rejeitado quando viola evidência. |
| T09 | Review approve/request_changes | Estado e notificações equivalentes. |
| T10 | Rejeições intercaladas por tarefa | Contador agregado igual ao algoritmo atual. |
| T11 | PRIOR_STATUS_MISMATCH e task.release | Exceção e reset preservados. |
| T12 | Cooldown e TTL em instantes controlados | Resultado temporal correto. |
| T13 | Dependências e superseded | Claim continua impedido quando necessário. |
| T14 | Cache ausente ou versão desconhecida | Caminho completo sem alteração da consulta. |
| T15 | Projeção modificada mantendo meta.hash | Cache rejeitado; verify identifica divergência. |
| T16 | Byte alterado no meio, mesmo tamanho | Conferência integral detecta mudança. |
| T17 | Log truncado, substituído ou acrescido | Cache e índices não aceitam vínculo antigo. |
| T18 | Manifesto com caminho fora do root | Não ler destino indevido; erro/fallback definido. |
| T19 | Manifesto sem uma view obrigatória | Não aceitar geração incompleta. |
| T20 | Perfil removido ou alterado | Ausência/presença e conteúdo tratados corretamente. |
| T21 | Contrato, swarm ou plugin muda sem novo evento | Contexto e cursores respeitam insumos atuais. |
| T22 | Pin/âncora externa muda com log igual | Falha de trust não é escondida por cache. |
| T23 | Snapshot com hash inválido ou outro workspace | Não restaurar; tratamento seguro e explícito. |
| T24 | Snapshot com agregado ausente | Versão incompatível ou validação rejeitada. |
| T25 | Nonce repetido depois do snapshot | Mesma rejeição do histórico integral. |
| T26 | Alias/principal divergente na entrega | Propriedade da tarefa preservada. |
| T27 | Rollback do store com pin à frente | Rejeição anti-rollback preservada. |
| T28 | Retry após alteração concorrente | Contexto e hashes refeitos corretamente. |
| T29 | Falha entre append e projeções | Recuperação deriva estado do log. |
| T30 | Falha na troca de geração | Leitor vê geração completa ou cai no caminho seguro. |
| T31 | Falha após log e antes do efeito final | Recovery não perde nem duplica efeito indevidamente. |
| T32 | Append sem newline anterior | Separador e offset corretos. |
| T33 | Unicode, CRLF e linhas vazias | Parser/índice equivalentes ao comportamento aceito. |
| T34 | Cauda incompleta | Erro canônico preservado, sem truncamento automático. |
| T35 | activity list com filtro raro | Paginação e has_more corretos. |
| T36 | after_seq entre checkpoints | Nenhum evento omitido ou repetido. |
| T37 | Consumidor reaplica mesmo evento | Idempotência ou deduplicação demonstrada. |
| T38 | Replay histórico | Nenhum efeito externo executado. |
| T39 | Runtime antigo diante de derivados novos | Compatibilidade/fallback de acordo com matriz. |
| T40 | Política com flag nova/valor inválido | Schema e comportamento coerentes. |
| T41 | Historicamente sem identidade vs autenticado | Cobertura e medições separadas. |
| T42 | Muitas candidatas com E fixo | Contagens de rejeição deixam de varrer E por tarefa. |
| T43 | Troca coerente de todos os arquivos locais sem trust | Limite de detecção documentado; não inventar garantia. |
| T44 | Consulta em diretório não inicializado | Nenhum arquivo criado, erro existente preservado. |

### 19.3 Testes existentes a reaproveitar

[[test_replay_performance.py|Testes de replay]] cobrem histórico rico, aplicação incremental, independência das views, respostas e caminhos de cache de digest, além de guardas de escala. [[test_grok_queries.py|Testes de queries]] cobrem paginação e consultas sem escrita. [[test_snapshot.py|Testes de snapshot]] e [[test_snapshot_compaction.py|compactação]] oferecem a base do formato atual.

Novos testes devem se apoiar nos invariantes que podem regredir. Evitar testes que apenas reproduzem a implementação ou fixam uma chamada interna sem relação com custo ou correção. Contar replay é apropriado quando a redução de reconstruções é o requisito que se pretende demonstrar.

### 19.4 Portões de aceite

| Portão | Condição mínima |
|---|---|
| Funcional | Projeções e respostas equivalentes nas cargas cobertas. |
| Integridade | Mesmos erros canônicos e nenhuma flexibilização silenciosa. |
| Segurança | Identidade/trust preservados ou caminho rápido explicitamente desabilitado. |
| Recuperação | Pontos de falha exercitados com resultado documentado. |
| Compatibilidade | Históricos antigos legíveis e política nova validada. |
| Desempenho | Contagens e medidas por carga, com comandos aceitos. |
| Documentação | Garantias, limites, migração e comandos publicados nas duas línguas quando aplicável. |
| Governança | Complete com checks reais, revisão autorizada e verify. |

### 19.5 Comandos existentes para validação futura

Os comandos abaixo são referências operacionais para uma futura implementação. Não foram executados como suíte desta entrega documental:

```bash
PYTHONPATH=src python -B -m pytest -q
PYTHONPATH=src python -B -m pytest -q tests/test_replay_performance.py tests/test_grok_queries.py tests/test_snapshot.py tests/test_snapshot_compaction.py
ESAA_RUN_PERFORMANCE_BENCHMARK=1 PYTHONPATH=src python -B -m pytest -q -s tests/test_replay_performance.py::test_acceptance_cli_claim_and_verify_50k
PYTHONPATH=src python -B -m esaa --root /caminho/do/workspace-de-teste verify
```

Executar a carga de aceitação em ambiente isolado e registrar o runner real nas operações de escrita. Consultar CONTRIBUTING e CI antes de definir o conjunto final de checks; mudanças em guias existentes exigem atualização do par português/inglês.

## 20. Plano incremental de implementação

### 20.1 Premissa de planejamento

Os itens abaixo são pacotes propostos, não tarefas já criadas ou autorizadas para código. O único trabalho governado desta entrega é a produção do documento e de suas fontes. Antes de executar cada pacote, criar/selecionar a tarefa correspondente, obter dispatch-context, observar lessons e limites, reivindicar e entregar pelo Orchestrator.

Não há estimativa de horas ou dias: o baseline de medições e a análise de dependências ainda precisam ser concluídos. A prioridade reflete redução de risco e dependência técnica, não uma promessa de prazo.

### 20.2 Pacotes e dependências

| Pacote | Entrega proposta | Dependência | Condição para avançar |
|---|---|---|---|
| P00 | Harness confiável e baseline por carga | Nenhuma mudança de runtime | Comandos aceitos, ambiente registrado e custos separados. |
| P01 | Reutilização de tarefa/estado dentro do comando | P00 | Equivalência e redução de replay demonstradas. |
| P02 | Agregados de tentativas e elegibilidade | P00; integração com P01 conveniente | Equivalência e retirada do termo E × K nas rejeições. |
| P03 | Conferência de append por cauda | P00 | Read-after-write e casos de newline/falha preservados. |
| P04 | Manifesto versionado e publicação de geração | P01; decisão de formato | Views consistentes e recuperação exercitada. |
| P05 | Leitura de derivados com conferência integral | P04; D-01 | Mesmas consultas e limites de confiança explícitos. |
| P06 | Índice de atividade por sequência/tarefa | P04 ou vínculo equivalente | Paginação correta e invalidação robusta. |
| P07 | Snapshot operacional para histórico legado | P01, P02, P04; D-02 | Restauração igual ao replay e ganhos medidos. |
| P08 | Snapshot e agregados de identidade/trust | P07; D-03 | Autorização, nonces e anti-rollback equivalentes. |
| P09 | Política de eventos verify e crescimento | P00; D-04; análise de compactação | Histórico antigo preservado e sem custo quadrático novo. |
| P10 | Consulta temporal e comparação de versões | P04; P07 opcional | Sem efeitos e com proveniência de ambiente limitada. |
| P11 | Consumidores e integrações derivadas | Necessidade concreta; D-08 | Idempotência, autorização e recovery demonstrados. |

P03 não depende de um cache de leitura e pode ser avaliado antes de P04. P09 é uma decisão semântica separada: não precisa bloquear a redução de replays. P08 pode revelar custos adicionais no caminho autenticado; não usar os resultados de P07 para anunciá-lo como resolvido.

### 20.3 Arquivos provavelmente envolvidos

| Pacote | Arquivos do baseline a examinar |
|---|---|
| P01 | submission, task_admin, verification_gate, verification_candidate, limit_revalidation, service_core, store. |
| P02 | execution, runtime_policy, seeds, projector e testes de política/elegibilidade. |
| P03 | store e testes de concorrência, corrupção e durabilidade. |
| P04/P05 | store, service_core, projection_check, queries, task_admin e schemas novos de derivados. |
| P06 | queries, store e testes de filtros, cursores e índices. |
| P07 | snapshot, projector, store, project_profile e novos testes de restauração. |
| P08 | identity_history, identity, trust_root, provenance e testes autenticados. |
| P09 | submission, orchestrator_commit, execution, service_core, snapshot, projector e schema de política. |
| P10/P11 | APIs de consulta, consumidores e documentação específica. |

Os nomes nesta tabela são abreviações dos módulos registrados no capítulo 25. A lista orienta a análise e não autoriza editar todos esses arquivos indiscriminadamente.

### 20.4 Revisão por pacote

Cada revisão deve receber problema, comportamento antes/depois, diff final, critérios, medições, compatibilidade e riscos. A revisão precisa testar o caminho que mudou e examinar o argumento de confiança. Não concluir que uma mudança é segura apenas porque usa as mesmas funções com parâmetros diferentes.

Mudanças que afetam garantias de leitura, confiança ou eventos canônicos devem ter decisão registrada antes da implementação. Mudanças locais de reaproveitamento de estado podem avançar dentro de tarefa autorizada sem pedir aprovação a cada escolha reversível.

## 21. Migração, compatibilidade e recuperação

### 21.1 Adoção por fases

PROP: introduzir formatos derivados sem alterar os eventos existentes; manter o caminho integral como referência; construir derivados por operação explícita; comparar em modo de avaliação; habilitar atalhos apenas para o escopo demonstrado; ampliar cobertura depois de validar confiança e recuperação.

Consultas não devem criar diretórios, head ou snapshots de modo incidental. A criação de derivados ocorre em comandos de escrita/manutenção autorizados, preservando o comportamento de diretórios não inicializados.

### 21.2 Avaliação paralela sem substituir o resultado

Um modo de avaliação proposto pode calcular resultado rápido e resultado integral, comparar e registrar divergências em artefato de diagnóstico autorizado. O resultado servido continua sendo o de referência durante essa fase. Isso permite detectar problemas de equivalência sem conceder autoridade ao cache prematuramente.

O custo adicional dessa avaliação é esperado e deve ser excluído das medições de desempenho do modo final. A gravação do diagnóstico precisa ser explícita; não introduzir efeitos em consultas comuns sob o nome de telemetria.

### 21.3 Compatibilidade de arquivos e leitores

Manter política clara para leitores antigos que esperam roadmap.json e outros caminhos atuais. Não trocar esses arquivos por links simbólicos ou apontadores sem verificar suporte e confinamento. Uma geração nova pode coexistir com os arquivos legados até a migração ser planejada.

Quando uma versão do runtime não entende o derivado, ela pode ignorá-lo e reconstruir pelo histórico, se esse histórico continuar suportado. Isso não implica que um runtime antigo possa ler qualquer evento novo. Compatibilidade de cache e compatibilidade do protocolo são questões separadas.

### 21.4 Contratos ativos e templates

OBS operacional desta entrega: a primeira tentativa de criar a tarefa documental com metadados G07 opcionais foi rejeitada pelo schema ativo do roadmap, que não aceitava task_type, acceptance_criteria e required_review_mode. A criação foi refeita usando campos suportados e critérios na descrição, sem alterar contratos. Essa ocorrência não impediu a entrega e não constitui autorização de migrar os schemas.

A lição aplicável à evolução é verificar capacidades reais de cada workspace. O template distribuído com o pacote não substitui automaticamente o contrato instalado. Alterações de formato e política devem oferecer migração explícita, dry-run quando pertinente e validação antes de qualquer efeito final.

### 21.5 Rollback de implementação

Desabilitar um atalho e voltar ao replay integral é uma recuperação possível quando o histórico continua legível e a decisão de confiança não alterou a fonte canônica. Caches e snapshots derivados podem ser descartados por operação autorizada; isso não deve apagar eventos.

Não confundir rollback do software com rollback do histórico: restaurar um log antigo pode violar checkpoint externo e deve continuar sendo rejeitado. Uma restauração de backup precisa seguir a política de recuperação e confiança, não remover o pin para fazer o comando passar.

### 21.6 Operação em falha

| Sintoma | Ação proposta |
|---|---|
| Cache inválido | Descrever o motivo e usar caminho integral se permitido. |
| Snapshot incompatível | Reconstruir pelo histórico ou informar incompatibilidade. |
| Projeção divergente | Preservar evidência e solicitar rebuild autorizado. |
| Histórico corrompido | Interromper operação e seguir ferramenta/política de repair. |
| Trust inconsistente | Interromper; não degradar para modo sem identidade. |
| Lock timeout | Relatar evidência; não remover lock manualmente. |
| Efeito de arquivo pendente | Usar recovery e verificar destino/artefatos. |
| Divergência entre modos | Desabilitar caminho otimizado no escopo afetado e investigar. |

## 22. Alternativas e decisões pendentes

### 22.1 Alternativas de armazenamento

| Alternativa | Onde pode ajudar | Limite no ESAA | Posição proposta |
|---|---|---|---|
| JSONL + derivados JSON | Simplicidade, inspeção e compatibilidade | Estado grande e publicação de arquivos completos | Manter como ponto de partida. |
| Índice de offsets local | Cauda e timeline | Exige vínculo e invalidação | Avaliar em P06. |
| SQLite como read model | Busca seletiva e índices persistentes | Acrescenta formato e mecanismo de reconstrução | Não descartar; decidir por benchmark. |
| SQLite/store transacional canônico | Transação e acesso por stream | Muda armazenamento e migração | Fora da primeira evolução. |
| Banco externo especializado | Distribuição e semântica de streams | Operação, dependências e mudança de contrato | Exige necessidade comprovada. |
| Kafka/filas | Consumidores distribuídos | Não remove custo de estado ou autorização | Adiar até P11 justificar. |
| Leitura em streaming | Redução de pico de memória | Pode continuar examinando todos os eventos | Avaliar por memória, sem prometer ganho universal de tempo. |
| Rotação/segmentação do log | Organização física e I/O seletivo | Fonte canônica e trust precisam de novo argumento | Estudo separado. |
| Processo persistente | Reutilizar memória entre comandos | Ciclo de vida, concorrência e operação adicionais | Alternativa futura, não premissa. |

O estudo não repete a rejeição absoluta a SQLite ou streaming sugerida em F03. A primeira escolha continua sendo otimizar os caminhos existentes; alternativas devem ser avaliadas pelos custos remanescentes medidos.

### 22.2 Registro de decisões

| ID | Decisão necessária | Recomendação técnica | Evidência para decidir |
|---|---|---|---|
| D-01 | Quais consultas podem servir derivados e com qual garantia? | Começar conservador; explicitar modo e proveniência | Equivalência, modelo de ameaça e custos reais. |
| D-02 | Qual confiança vincula snapshot ao prefixo? | Não equiparar hash local a autenticidade | Testes de substituição e análise de armazenamento. |
| D-03 | Quando habilitar otimização autenticada? | Só após provar agregados, nonces e trust | B07, T22 e T25–T28. |
| D-04 | Manter, omitir ou substituir verify.start/ok? | Tratar como mudança semântica versionada | Volume em bytes, consumidores e compactação. |
| D-05 | Gerações e manifesto serão internos ou públicos? | Minimizar ruptura de caminhos legados | Inventário de leitores e recuperação. |
| D-06 | Metas de latência e memória por host/carga? | Fixar depois de P00 | Amostras reproduzíveis e critérios de produto. |
| D-07 | JSON ou outro mecanismo de read model? | Adiar decisão até medir o estado atual | B12 e custo de consultas seletivas. |
| D-08 | Haverá consumidores externos e efeitos novos? | Autorizar por integração concreta | Destino, credenciais, idempotência e escopo. |
| D-09 | Garantia de atualidade de dispatch-context? | Informar sequência e revalidar no commit | Experiência do agente e corridas observadas. |
| D-10 | Política de retenção de gerações e snapshots? | Manter recuperação sem crescimento ilimitado | Espaço, leitores concorrentes e testes de limpeza. |

Essas decisões não estão resolvidas pela aprovação deste documento como material de estudo. O registro final de cada decisão deve indicar responsável, data, justificativa e escopo.

## 23. Riscos e rastreabilidade das propostas

### 23.1 Registro de riscos

| Risco | Causa | Mitigação | Evidência de controle |
|---|---|---|---|
| Aceitar estado adulterado | Cache local tratado como autoridade | Perfis de confiança e caminho integral | T15–T18, T22, T43. |
| Misturar projeções | Publicação por arquivo sem geração | Manifesto e vínculo de sequência | T19, T29, T30. |
| Perder regras no snapshot | Serializar apenas roadmap | Inventário completo de agregados | T01, T23–T27. |
| Reutilizar contexto obsoleto | Estado anterior ao lock | Contexto transacional e retry | T05, T28. |
| Omitir evento em índice | Offset/linha/filtro incorreto | Sequência validada e paginação por resultado | T33–T36. |
| Reexecutar efeito histórico | Misturar replay e execução | APIs separadas e teste de ausência de efeitos | T31, T38. |
| Voltar ao custo quadrático | Hash completo por lote ou varredura por tarefa | Instrumentação de trabalho e curvas de escala | B03, B07, T42. |
| Confundir falha rápida com ganho | Harness ignora status | Validar saída e abortar amostra inválida | P00 e portão funcional. |
| Regressão em workspace antigo | Copiar templates sobre contratos | Migração explícita e matriz de suporte | T39, T40. |
| Crescimento de derivados | Gerações e checkpoints sem retenção | Política de manutenção segura | D-10 e testes de leitores concorrentes. |
| Exposição de credenciais | Telemetria/cópia indiscriminada de trust | Dados sintéticos e minimização | Inspeção dos artefatos e fixtures. |

### 23.2 Matriz fonte, achado e ação

| Fonte | Ideia ou evidência | Aplicação proposta | Validação |
|---|---|---|---|
| F01, trecho de separação de modelos | Consultas têm representação própria | P04/P05 e capítulo 10 | Equivalência e confiança. |
| F01, consistência eventual | Leitura pode ficar atrás da escrita | Sequência da geração e exigência de atualidade | T21, T28, T30. |
| F01, dupla escrita | Publicação externa pode falhar | P11 e consumidor idempotente | T37 e recovery. |
| F02, snapshot e cauda | Evitar reconstrução desde a origem | P07/P08 | T01, T23–T28. |
| F02, streams | Histórico agrupado por entidade | P06 com índices lógicos | T35/T36. |
| F02, replay temporal | Investigar estados passados | P10 | T38 e metadados de versão. |
| F03, replays repetidos | Estado já disponível é reconstruído | P01 | T03–T09 e contadores. |
| F03, head com hashes | Conferir projeções antes de usá-las | P04/P05 com limites explícitos | T14–T22, T43. |
| F03, verify.* | Eventos auxiliares dominam contagem | P09 após decisão | Volume e compatibilidade. |
| F04, gerador sintético | Base de medição disponível | P00 com correções de harness | B01–B12. |
| Código de eligible | Varreduras por tarefa | P02 | T10–T13, T42. |
| Código de trust | Proteções dependem de estado externo | P08 separado | B07 e anti-rollback. |
| Snapshot atual | Artefato não usado como base de execução | Novo formato operacional | Restauração e fallback. |

### 23.3 Relação com a auditoria existente

ARQ-01 orienta evitar reconstruções e validar escala; o baseline b26 já tratou parte desse problema. FUN-04 orienta reduzir eventos auxiliares com semântica explícita. AUD-O2-040 descreve a ambição de snapshot com cauda. As propostas daqui detalham esses caminhos e acrescentam dependências de confiança e publicação.

Não se presume que os IDs da auditoria estejam disponíveis para claim. Na consulta feita durante a análise, o ID literal AUD-O2-040 não estava cadastrado no roadmap. O planejamento futuro precisa conferir o estado real e evitar duplicidade ou alegação de execução de tarefa inexistente.

## 24. Conclusões técnicas e limites da entrega

### 24.1 Direção recomendada

O ESAA-Core já utiliza Event Sourcing e possui elementos de separação entre comando e consulta. A evolução mais útil é transformar os resultados já derivados em componentes operacionais reutilizáveis, com contratos de validade, atualização e recuperação.

A prioridade técnica proposta é: medir; retirar reconstruções redundantes dentro de cada comando; agregar tentativas numa passagem; reduzir releituras físicas evitáveis; estabelecer gerações consistentes; habilitar consultas por derivados no escopo demonstrado; implementar snapshot operacional; tratar identidade autenticada como etapa própria; decidir separadamente sobre eventos de verificação e integrações.

### 24.2 O que este estudo não demonstra

Este estudo não demonstra latências novas a 50 mil, 200 mil ou 500 mil eventos; não valida os diffs de F03; não comprova desempenho autenticado; não aprova enfraquecimento de integridade; não demonstra comportamento em produção. Os algoritmos propostos ainda precisam ser implementados e passar pelos portões de aceite.

A entrega documental pode ser concluída e submetida para revisão sem que nenhuma dessas implementações esteja concluída. O estado administrativo da tarefa não deve ser usado como evidência de implementação ou de autorização de publicação.

### 24.3 Próxima ação concreta

Criar uma proposta de execução para P00 e P01 com escopo de arquivos, critérios, medições e revisão. P02 pode ser preparado com os mesmos dados de baseline. As decisões D-01 a D-03 devem anteceder a ativação de atalhos que alterem a confiança em projeções ou snapshots.

### 24.4 Verificações desta entrega documental

Foram verificados: frontmatter e autoria; sequência dos 25 capítulos; resolução das 25 entradas do sumário; estrutura GFM das tabelas; fechamento dos blocos de código; sintaxe dos exemplos JSON e do pseudocódigo Python; existência dos artefatos internos registrados; igualdade dos bytes das quatro cópias com as fontes originais; hashes de proveniência; existência dos símbolos de código usados como evidência central. Os wikilinks do estudo foram resolvidos pelo índice, sem pendências.

O comando verify retornou ok após a criação e a reivindicação da tarefa documental. A entrega final usa file_updates pelo Orchestrator e deve ser seguida de verify. A revisão desta versão é autoral e estrutural; não foi realizada revisão independente por outro agente ou humano. Nenhuma suíte de implementação ou benchmark de escala foi executada por esta entrega de documentação.

## 25. Referências e proveniência

### 25.1 Fontes fornecidas e preservadas

As cópias abaixo preservam os bytes originais recebidos. Elas não carregam aprovação técnica implícita e não foram executadas por terem sido anexadas.

| ID | Cópia preservada | Bytes | SHA-256 |
|---|---|---:|---|
| F01 | [[fonte-cqrs.txt\|DC-fonte-cqrs-v1.0.txt]] | 33062 | `e21a1d040c9b804f050a02b299377f687a3717dcb7c79ceed4d8f50660e2cb9f` |
| F02 | [[fonte-event-sourcing.txt\|DC-fonte-event-sourcing-v1.0.txt]] | 41493 | `239fe0fbafe12a05b984ea82846c3ed61ffcbc9816badd23f9b79876e663f6c4` |
| F03 | [[fonte-proposta-fable\|DC-fonte-proposta-fable-v1.0.md]] | 14629 | `9d65a3cffb757125379ed77df467dad248d3059abef595578da160eeb6c735bc` |
| F04 | [[bench_esaa.py\|bench_esaa.py]] | 3794 | `a5e772077e4807086ec40551c60432b0d4b66dfbcea75680c8e9c8ea7c5552fc` |

- **F01 — origem recebida:** `/home/elzobrito/.codex/attachments/55a04976-981b-46a9-ae88-3ce83a225280/Texto colado.txt`.
- **F02 — origem recebida:** `/home/elzobrito/.codex/attachments/d43b2d21-18ab-4b49-be7a-dba2c5ec2697/Texto colado.txt`.
- **F03 — origem recebida:** `/home/elzobrito/Downloads/custo-leitura-esaa.md`.
- **F04 — origem recebida:** `/home/elzobrito/Downloads/bench_esaa.py`.

### 25.2 Trechos usados das transcrições

| Fonte | Linhas do original lógico | Assunto usado |
|---|---|---|
| F01 | 261–280 | Diagnóstico de custo e separação de responsabilidades. |
| F01 | 283–339 | Modelos distintos de escrita e consulta. |
| F01 | 343–385 | Sincronização, CDC, mensageria e dupla escrita. |
| F01 | 395–430 | Atraso de projeção e aplicação localizada do padrão. |
| F02 | 282–315 | Streams associados a uma entidade. |
| F02 | 320–404 | Projeções para leitura e derivação de estado. |
| F02 | 405–483 | Decisão de negócio, snapshots e eventos posteriores. |
| F02 | 490–536 | Reconstrução temporal e múltiplas projeções. |
| F03 | Seções 1–4 | Contagens propostas, quatro camadas e expectativas não medidas. |
| F04 | 10–37 e 39–70 | Preparação do histórico e método de medição. |

Os números de linha orientam localização nas cópias preservadas; erros de transcrição não foram normalizados. O texto deste estudo desenvolve propostas próprias e não adota as generalizações dos vídeos como prova de escalabilidade.

### 25.3 Referências externas

- **F05 — Fowler, Martin. CQRS.** 14/07/2011. [Texto original](https://martinfowler.com/bliki/CQRS.html). Referência para separar modelos sem impor bancos ou serviços distintos.
- **F06 — Fowler, Martin. Event Sourcing.** 12/12/2005, texto de trabalho histórico. [Texto original](https://martinfowler.com/eaaDev/EventSourcing.html). Referência para derivação de estado, snapshots e reconstrução temporal.
- **F07 — Microsoft. CQRS pattern. Azure Architecture Center.** [Documentação oficial](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs). Referência complementar sobre responsabilidades de modelos e trade-offs.
- **F08 — Microsoft. Event Sourcing pattern. Azure Architecture Center.** [Documentação oficial](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing). Referência complementar sobre histórico, consistência e evolução.

Todas consultadas em 12/11/2026. O conteúdo externo não define as regras operacionais do workspace; contratos e políticas locais continuam sendo a autoridade.

### 25.4 Mapa de evidências do código no baseline

| ID | Arquivo | Pontos de interesse no commit de referência |
|---|---|---|
| C01 | [[store.py\|store.py]] | 225–335: parser/digest; 478–488: conferência; 555–660: transação. |
| C02 | [[projector.py\|projector.py]] | 75–82: hash; 394–437: aplicação; 476–535: replay e views. |
| C03 | [[submission.py\|submission.py]] | 129–167: estado e gate; 227–265: lote e commit. |
| C04 | [[task_admin.py\|task_admin.py]] | 152–193: consultas; 233–324: complete/review; 432–451: admissão. |
| C05 | [[service_core.py\|service_core.py]] | 202–283: project/verify; 293–350: transação e retries. |
| C06 | [[queries.py\|queries.py]] | 1: regra de confiança; 29–100: tarefas; 103–138: atividade. |
| C07 | [[execution.py\|execution.py]] | 64–115: elegibilidade e varreduras por tarefa. |
| C08 | [[runtime_policy.py\|runtime_policy.py]] | 53–66: schema; 100–146: tentativas; validação de runners. |
| C09 | [[seeds.py\|seeds.py]] | 356–407: seleção e agrupamento de conflitos. |
| C10 | [[verification_gate.py\|verification_gate.py]] | 18–56: evidência; 85–109: lote pendente. |
| C11 | [[verification_candidate.py\|verification_candidate.py]] | 52–132: tarefa, entradas e vínculo do candidato. |
| C12 | [[limit_revalidation.py\|limit_revalidation.py]] | 11–24: revalidação de limites sob lock. |
| C13 | [[snapshot.py\|snapshot.py]] | 54–93: criação; 96–139: compactação; 144–160: replay. |
| C14 | [[identity_history.py\|identity_history.py]] | 77 em diante: validação cronológica e confiança externa. |
| C15 | [[trust_root.py\|trust_root.py]] | 132–249: pin, checkpoint e avanço; 278–297: monotonicidade. |
| C16 | [[identity.py\|identity.py]] | Autorização, papéis, principais e separação de revisão. |
| C17 | [[projection_check.py\|projection_check.py]] | Comparação integral das projeções armazenadas. |
| C18 | [[orchestrator_commit.py\|orchestrator_commit.py]] | Preparação de lote e refresh de hashes em retry. |
| C19 | [[file_effects.py\|file_effects.py]] | Staging, commit, confinamento e recovery de arquivos. |
| C20 | [[project_profile.py\|project_profile.py]] | Derivação e normalização do perfil. |
| C21 | [[runtime_policy.schema.json\|runtime_policy.schema.json]] | Chaves admitidas e restrições da política distribuída. |
| C22 | [[cli.py\|cli.py]] | Sintaxe, runner, consultas e flags de paginação. |
| C23 | [[test_replay_performance.py\|test_replay_performance.py]] | Equivalência, cache e aceitação condicional de 50 mil eventos. |
| C24 | [[test_grok_queries.py\|test_grok_queries.py]] | Consultas sem escrita, filtros e cursores. |
| C25 | [[test_snapshot.py\|test_snapshot.py]], [[test_snapshot_compaction.py\|test_snapshot_compaction.py]] | Semântica atual dos artefatos de snapshot. |

As linhas são localizadores do baseline e podem mudar depois de alterações no código. O commit completo da capa é a referência para reproduzir a leitura.

### 25.5 Referências internas e backlinks

**Este documento referencia:**

- [[fonte-cqrs.txt|F01 — transcrição CQRS]] e [[fonte-event-sourcing.txt|F02 — transcrição Event Sourcing]] — fontes conceituais fornecidas pelo usuário.
- [[fonte-proposta-fable|F03 — proposta Fable]] e [[bench_esaa.py|F04 — benchmark]] — proposta anterior e método de medição inspecionado.
- [[auditoria-esaa-20261110|Auditoria técnica]] e [[changelog-esaa|CHANGELOG]] — diagnóstico histórico e correção b26.
- [[agentes-esaa|AGENTS.md]], [[contrato-agente.yaml|contrato do agente]], [[contrato-orchestrator.yaml|contrato do Orchestrator]], [[agent_result.schema.json|schema de envelope]] e [[politica-runtime.yaml|política ativa]] — autoridade operacional.
- Os módulos e testes relacionados no mapa C01–C25 — evidência de implementação no baseline.
- [[contribuir-esaa|CONTRIBUTING]] e [[guia-runners-esaa|guia de runners]] — procedimento de contribuição e submissão.
- [[indice-referencias|Índice de referências]] — resolução dos nomes de artefatos.

**Este documento é referenciado por:**

- [[indice-referencias|Índice de referências]] — registro de descoberta e navegação deste estudo.
- Tarefa documental `ARCH-CQRS-ES-DOC-20261112` — referência de entrega governada, sem modificar sua projeção manualmente.

---

**Versão 1.0 — 12/11/2026 — Codex — Proposta para revisão.**
