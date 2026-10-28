# 03 - Execução

Este documento conta como o projeto foi construído, na ordem em que as coisas aconteceram: o que foi feito, por que daquele jeito e o que deu errado no caminho.

## Visão geral das etapas

| # | Etapa | Entregável |
|---|---|---|
| 1 | Webhook | Lambda com verificação da Meta, assinatura HMAC e normalização do payload |
| 2 | Domínio da conversa | Estados `bot`, `waiting_human` e `human`, regras de handoff |
| 3 | Agente | Loop de tool calling com identidade injetada |
| 4 | Processamento | Caso de uso com idempotência, mídia, handoff e contingência |
| 5 | Loja e MCP | Regras de pedido, rastreio, troca e chamado expostas via MCP |
| 6 | Infraestrutura | MongoDB, Graph API, SQS, S3, LocalStack e bootstrap |
| 7 | API e simulador | Painel, Graph API falsa, simulador assinado e SSE |
| 8 | Front-end | Celular simulado e painel em tempo real |
| 9 | Testes, smoke e evals | Unitários, integração com AWS emulada, ponta a ponta e cenários com LLM |
| 10 | Terraform e pipeline | AWS real com OIDC e CI completo |
| 11 | Teste com LLM real | Parâmetros do modelo, ajuste do prompt guiado pelos evals e conversa real |

---

## Etapa 1: webhook

**Objetivo:** responder à Meta em milissegundos e nunca aceitar uma chamada que não veio dela.

- **Verificação (`GET`):** a Meta chama com `hub.mode=subscribe`, `hub.verify_token` e `hub.challenge`; a Lambda devolve o `challenge` se o token bater.
- **Assinatura (`POST`):** `X-Hub-Signature-256: sha256=<HMAC do corpo com o app secret>`. A comparação usa `hmac.compare_digest` (tempo constante), e um segredo vazio **nunca** valida, para evitar que uma configuração esquecida abra o webhook.
- **Normalização:** extraio só o que importa (id, telefone, nome, tipo, texto, mídia) e ignoro notificações de status (`sent`, `delivered`, `read`), que chegam pelo mesmo webhook.
- O código da Lambda **não importa nada** do resto do projeto, só a stdlib e o `boto3` que já existe no runtime. O pacote tem poucos KB e não precisa de layer.

A assinatura é calculada sobre os **bytes exatos** do corpo. Por isso a Lambda lida com `isBase64Encoded` (o API Gateway pode entregar o corpo em base64) antes de validar.

## Etapa 2: domínio da conversa

Modelei a conversa como máquina de estados na entidade `Conversation`. As transições inválidas lançam `InvalidTransition`: por exemplo, um segundo atendente tentando assumir uma conversa que já tem dono.

A detecção de "quero falar com um atendente" é uma **regra determinística** (regex sobre o texto normalizado, sem acentos), aplicada **antes** do LLM. É mais barata, funciona com o LLM fora do ar e não depende do modelo "entender". Os testes cobrem também falsos positivos: "humanidade" não pode disparar a transferência.

## Etapa 3: o agente

O `RunAgent` segue o loop clássico de tool calling, com uma diferença importante: a **identidade injetada** ([ADR 0003](adr/0003-identidade-injetada-nas-ferramentas.md)).

1. Lista as ferramentas do MCP e **remove `telefone`** de cada schema, inclusive da lista `required`.
2. A cada chamada, monta `{**argumentos_do_modelo, "telefone": telefone_da_conversa}`, então o valor do servidor sempre vence.
3. Publica `tool_started` e `tool_finished` para o painel.
4. Se a ferramenta `transferir_para_humano` der certo, encerra com a mensagem padrão de transferência e o protocolo.
5. Erros de regra da loja ("prazo de troca expirado") voltam ao modelo como `ERRO: ...`, para ele explicar ao cliente.
6. Ao estourar o limite de passos, transfere para humano em vez de responder qualquer coisa.

O histórico vira mensagens do modelo: o cliente como `user`, o bot e o atendente como `assistant` (o atendente com prefixo `[atendente Nome]`), e mídias aparecem como referência ao objeto no S3.

## Etapa 4: processamento da mensagem

O `ProcessInboundMessage` orquestra tudo, e a ordem importa:

1. **Claim de idempotência** ([ADR 0002](adr/0002-idempotencia-no-consumidor.md)).
2. Carrega ou cria a conversa.
3. Baixa a mídia pela Graph API e guarda no S3.
4. Registra a mensagem e publica o evento.
5. Se a conversa não está com o bot, para aqui.
6. Se o cliente pediu atendente, transfere.
7. Senão, roda o agente. **Qualquer exceção do agente vira contingência + transferência.**
8. Responde pela Graph API e registra.

Se algo de infraestrutura falhar (Graph API, MongoDB, S3), a exceção sobe, o claim é liberado e a mensagem volta para a fila.

> **Problema encontrado:** ao escrever o teste de retentativa, percebi que a mensagem do cliente aparecia **duas vezes** no painel. A primeira tentativa registrava a mensagem e só depois falhava ao responder; na segunda tentativa, ela era registrada de novo.
>
> **Correção:** o histórico passou a usar *upsert* por `message_id` (`$setOnInsert`), com um índice único parcial (só para documentos que têm `message_id`, já que respostas do atendente não têm).

## Etapa 5: loja e servidor MCP

O contexto da loja é separado do contexto da conversa: o worker só conversa com ele por MCP.

- `StoreService` concentra as regras:
  - o pedido precisa pertencer ao telefone;
  - troca só de pedido entregue há no máximo 30 dias;
  - coleta a partir de amanhã, em até 30 dias e nunca no domingo;
  - uma troca aberta por pedido.
- Para pedido inexistente e pedido de outro cliente, a mensagem é **a mesma**. Assim, nem a existência do pedido vaza.
- Relógio e gerador de protocolo são injetáveis, então os testes usam uma data fixa e protocolos previsíveis.
- O seed gera pedidos com datas **relativas a hoje** (entregue há 5 dias, há 45 dias...), para os cenários de troca continuarem válidos em qualquer dia em que o projeto rodar.

## Etapa 6: infraestrutura e LocalStack

O `bootstrap` é um container que roda uma vez e é **idempotente**:

1. inicia o replica set do MongoDB;
2. cria o bucket, a DLQ, a fila com `RedrivePolicy` (3 recebimentos) e visibilidade de 60s;
3. empacota a Lambda num zip em memória e cria ou atualiza a função;
4. cria o API Gateway com ID fixo (`_custom_id_`), para a URL do webhook ser previsível;
5. popula a loja.

Decidi de antemão usar `SQS_ENDPOINT_STRATEGY=path` com `LOCALSTACK_HOST=localstack:4566`. O padrão do LocalStack gera URLs de fila com o host `sqs.us-east-1.localhost.localstack.cloud`, que dentro dos containers resolve para `127.0.0.1`.

> **Problema encontrado:** na primeira execução, o `bootstrap` ficou vários minutos consultando `GetFunction`, com a Lambda presa em `Pending`, sem nenhum erro no log.
>
> **Causa:** o LocalStack executa a Lambda num container próprio e, na primeira vez, baixa a imagem de runtime Python 3.12. Até isso terminar, a função fica `Pending`.
>
> **Correção:** nenhuma no código. O `bootstrap` já usa o waiter `function_active_v2`. Documentei no README e na pipeline que o primeiro `up` é lento e que o LocalStack precisa do socket do Docker.

> **Problema encontrado:** a cada `docker compose up`, o `bootstrap` republicava a Lambda, e a próxima mensagem pagava um *cold start*. Com a máquina carregada, ele passou dos 30s, e a chamada do simulador estourou o timeout (a mensagem chegou ao worker, mas a resposta HTTP ao simulador não veio a tempo).
>
> **Correção, em duas partes:**
> - O `bootstrap` compara o `CodeSha256` da função com o hash do zip e só republica se o código mudou.
> - O zip precisava ser **determinístico**: ele carregava o *mtime* dos arquivos, que muda a cada build da imagem. Passei a montar cada entrada com `ZipInfo` e data fixa.
>
> **Regressão que essa correção causou:** depois dela, a Lambda passou a responder `502`. No log do LocalStack: `PermissionError: [Errno 13] Permission denied: '/var/task/zapagent/__init__.py'`. Um `ZipInfo` criado à mão vem com `external_attr = 0`, ou seja, arquivos sem permissão nenhuma. O `archive.write` copiava as permissões do disco, e eu tinha perdido isso sem perceber.
>
> **Correção:** `external_attr = 0o644 << 16`. Criei também um teste unitário que verifica que o zip é determinístico e que toda entrada tem permissão de leitura, para essa regressão não voltar.
>
> **Lição:** foi o teste de integração contra uma Lambda de verdade (no LocalStack) que pegou o problema. Um mock do `boto3` teria passado.

> **Problema encontrado:** o LocalStack Community não tem API Gateway HTTP API (v2), que é o que eu queria usar na AWS por ser mais barato e simples.
>
> **Correção:** localmente uso REST API (v1); no Terraform, HTTP API (v2). A Lambda aceita os dois formatos de evento (`httpMethod` no v1, `requestContext.http.method` no v2), e há teste parametrizado para os dois, inclusive com corpo em base64.

## Etapa 7: API, simulador e tempo real

- A **Graph API falsa** tem as mesmas rotas e o mesmo formato de resposta da real e exige o mesmo `Bearer` token. O worker não sabe se está falando com a Meta ou com o simulador.
- O **simulador** monta o payload igual ao da Meta, **assina com o app secret** e chama o webhook pelo API Gateway. A mensagem percorre o mesmo caminho de produção, sem atalhos.
- O **tempo real** usa change streams do MongoDB: worker e API gravam eventos numa coleção, e a API transforma cada inserção num evento SSE. Como o worker e a API são processos diferentes, o banco é o barramento. Change streams exigem replica set, por isso o MongoDB sobe com `--replSet rs0`.
- O stream SSE usa `try_next()` com `max_await_time_ms`, para mandar um `: ping` a cada 10s sem eventos. Isso mantém a conexão viva através de proxies e permite detectar quando o cliente desconectou.

## Etapa 8: front-end

- React + Vite, no mesmo padrão visual do InsightQL, com tema claro e escuro.
- À esquerda, um celular com os contatos do seed e anexo de imagem; à direita, o painel com a fila, o histórico, as ferramentas MCP chamadas (com argumentos e resultado) e os botões de assumir e devolver.
- `EventSource` nativo (o stream é `GET`), com indicador de conexão.
- O painel **esconde o parâmetro `telefone`** na lista de ferramentas, porque ele é detalhe de infraestrutura, não decisão do agente.

## Etapa 9: testes, smoke e evals

**Unitários:** webhook, domínio, agente com modelo roteirizado, processamento com fakes em memória, regras da loja.

**Integração** (MongoDB e LocalStack reais):
- webhook assinado atravessando API Gateway → Lambda → SQS;
- assinatura forjada recusada com `401` pela Lambda;
- `hub.challenge` respondido;
- mensagem envenenada indo para a DLQ;
- idempotência e upsert no MongoDB;
- ferramentas MCP contra a loja populada.

> **Problema encontrado:** o teste da DLQ falhou na primeira execução, mesmo com a `RedrivePolicy` aplicada corretamente.
>
> **Investigação:** rodei o mesmo fluxo manualmente e imprimi o `ApproximateReceiveCount`. A mensagem foi recebida 3 vezes e só foi movida para a DLQ **na tentativa seguinte de recebimento**. O teste original fazia um número fixo de iterações, que nem sempre chegava ao quarto recebimento.
>
> **Correção:** o teste passou a ser orientado a condição: recebe, espera a visibilidade expirar e verifica a DLQ, até 20 vezes.
>
> **Lição:** teste de infraestrutura assíncrona deve esperar por um estado, não contar passos.

**Smoke ponta a ponta** (`zapagent.entrypoints.smoke`, roda dentro do container da API):
1. mensagem assinada pelo simulador;
2. resposta entregue no celular;
3. atendente assume e responde;
4. o bot fica calado durante o atendimento humano;
5. a conversa é devolvida;
6. a imagem enviada vai para o S3.

**Evals:** oito cenários com LLM real, cobrindo:
- ferramenta correta (consultar, rastrear, trocar, chamado);
- pedir o número quando falta;
- recusa de troca fora do prazo;
- **não vazar pedido de outra cliente**;
- transferir cliente irritado.

As datas de coleta são geradas em tempo de execução para nunca caírem no passado nem num domingo.

## Etapa 10: containers, Terraform e pipeline

- Um único Dockerfile multi-stage do backend gera as imagens de `test`, `evals` e `runtime`. A mesma imagem `runtime` roda API, worker, MCP e bootstrap, só com comandos diferentes.

> **Problema encontrado:** o compose estava construindo a mesma imagem do backend **quatro vezes em paralelo** (bootstrap, mcp-server, api e worker tinham `build`). Com a máquina já carregada, isso multiplicava o tempo e a memória do build. Ao dar a mesma tag a todos, o build falhou com `image "zapagent-backend:local": already exists`, porque cada serviço tentava exportar a mesma imagem.
>
> **Correção:** só o `bootstrap` declara `build`. Os demais usam `image: zapagent-backend:local` com `pull_policy: never`, e o compose constrói a imagem uma vez antes de criar os containers.

> **Problema encontrado:** com a máquina sob carga, a stack não ficava saudável. Investigando com `docker top`, achei **quatro processos `mongosh` simultâneos** no container do MongoDB, cada um rodando havia mais de um minuto. O healthcheck usava `mongosh` (um runtime Node.js) a cada 5 segundos. Sob carga, cada execução passava do timeout, e as execuções se acumulavam e disputavam a CPU com o próprio banco.
>
> **Correção:** removi o healthcheck do MongoDB. A iniciação do replica set foi para o `bootstrap`, em Python com `pymongo`: ele espera o banco aceitar conexões, chama `replSetInitiate` (tratando o código 23, "já iniciado") e aguarda virar primário. Isso acontece uma vez, não a cada 5 segundos. O healthcheck da API ganhou `start_period` e timeout maior pelo mesmo motivo.
>
> **Lição:** healthcheck também consome recurso. Ele precisa ser barato e não pode ser mais pesado que o serviço que verifica.

- O **Terraform** empacota a Lambda com `archive_file` direto do código-fonte (sem passo de build) e cria a HTTP API, a fila com DLQ e criptografia gerenciada, o bucket privado com expiração e uma política IAM mínima para o worker.
- A **pipeline** testa tudo com Docker. O deploy é manual, via OIDC (sem chave de acesso fixa), restrito ao environment `production`.

## Etapa 11: primeiro teste com um LLM real

Até aqui o agente só tinha rodado com modelo roteirizado e pelo caminho de contingência. Com a OpenAI (`gpt-5.6-luna`), apareceram três coisas.

> **Problema 1: parâmetros do modelo.** O adaptador enviava `temperature=0` fixo. Modelos de raciocínio recusam `temperature`, e esse modelo também recusa `reasoning_effort` junto com *function calling* no endpoint de chat.
>
> **Correção:** `LLM_TEMPERATURE` e `LLM_REASONING_EFFORT` passaram a ser opcionais e só vão na requisição quando configurados. Com o `gpt-5.6-luna`, uso `LLM_REASONING_EFFORT=none`. Dois testes novos garantem o comportamento.

> **Problema 2: o agente transferia cedo demais.** No eval `troca-fora-do-prazo`, a ferramenta recusou a troca corretamente ("prazo de 30 dias após a entrega"), mas o agente chamou `transferir_para_humano` na mesma resposta, e o cliente recebeu só "vou te transferir", sem saber por quê. O prompt dizia para transferir "quando uma ferramenta recusar a solicitação **e o cliente insistir**", mas o modelo leu como duas condições separadas.
>
> **Correção:** separei em duas regras: primeiro explicar a recusa com as informações que a ferramenta devolveu, sem transferir na mesma resposta; transferir só se o cliente insistir. O agente passou a responder "o pedido 1003 foi entregue em 13/09/2026, ultrapassando o prazo de 30 dias para troca". A acurácia dos evals foi de 88% para 100%.
>
> **Lição:** regra com "e" num prompt é ambígua para o modelo. Uma regra por condição funciona melhor.

> **Problema 3: um teste de integração falhou depois da correção.** `test_signed_webhook_goes_through_api_gateway_and_lambda_to_sqs` envia uma mensagem e confere se ela chegou ao SQS. Rodei a suíte com a stack de pé, e o worker consumiu a mensagem antes da asserção.
>
> **Correção:** nenhuma no código; com a stack derrubada, os 57 testes passaram. É o mesmo cenário da pipeline, que sobe só o que os testes precisam. Fica a anotação: testes de integração e stack de desenvolvimento não devem dividir a mesma fila.

Conversa real pelo simulador, com a stack completa:

- **Dono do pedido:** "Qual o status do pedido 1005?" → o agente consultou o MongoDB e respondeu que o pedido está cancelado, com valor e produto. Na mensagem seguinte ("quando chega?"), manteve o contexto.
- **Pedido de outro cliente:** outra pessoa perguntando pelo mesmo pedido recebeu "não encontrei o pedido vinculado aos seus dados". A identidade vem do número do WhatsApp, não do que o cliente digita.
- **"Quero falar com um atendente":** a conversa foi para `waiting_human` com o motivo registrado.
- **Tempo de resposta:** de 1 a 7 segundos por mensagem, passando por API Gateway, Lambda, SQS, worker, MCP e OpenAI.

---

## Validações realizadas

| Verificação | Resultado |
|---|---|
| Backend: unitários + integração (MongoDB e LocalStack reais), via compose | 57 aprovados |
| Webhook assinado: API Gateway → Lambda → SQS | OK |
| Assinatura forjada | Recusada com `401` pela Lambda |
| Verificação `hub.challenge` | OK |
| Mensagem envenenada | Movida para a DLQ |
| Front: typecheck + Vitest | 4 aprovados |
| Smoke ponta a ponta, sem LLM configurado | OK: contingência, fila humana, atendente assume/responde/devolve, bot calado durante o atendimento, imagem no S3 |
| Stream SSE (change stream → painel) | Evento `status_changed` recebido em tempo real |
| Workflow validado com actionlint | Sem erros |
| `terraform fmt -check` e `terraform validate` | Sem diferenças / configuração válida |
| Evals com LLM real (`gpt-5.6-luna`, 8 cenários) | 100% após o ajuste do prompt (antes, 88%) |
| Conversa real pelo simulador com LLM | Consulta, contexto, isolamento entre clientes e handoff funcionando |

## Próximos passos

- Worker e API em ECS Fargate, com autoscaling pelo tamanho da fila.
- Templates de mensagem aprovados pela Meta, para mensagens fora da janela de 24h.
- Transcrição de áudio antes de chamar o agente.
- Status do claim (`processing`/`done`) com expiração, para recuperar mensagens de um worker que morreu no meio do processamento.
- Segredos da Lambda no Secrets Manager em vez de variáveis de ambiente.
- Autenticação no painel de atendimento.
