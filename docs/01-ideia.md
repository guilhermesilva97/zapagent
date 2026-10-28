# 01 - Ideia

## O problema

Atendimento por WhatsApp virou o canal principal de muitas lojas online, e a maior parte das mensagens é repetitiva: "cadê meu pedido?", "qual o código de rastreio?", "quero trocar". Ao mesmo tempo, os bots tradicionais de menu ("digite 1 para...") frustram o cliente, e os bots com IA sem controle inventam prazos e status.

Já trabalhei com integração direta com a plataforma da Meta em ambiente corporativo, substituindo uma solução terceirizada. O ZapAgent é a reconstrução dessa experiência do zero, com dados fictícios, juntando três coisas que eu queria demonstrar num só projeto: integração real com a WhatsApp Cloud API, arquitetura serverless orientada a filas na AWS e um agente de IA que **só fala o que as ferramentas confirmam**.

## O que eu queria provar

1. Que um webhook da Meta pode ser **seguro e barato**: assinatura validada, resposta em milissegundos e processamento assíncrono numa fila.
2. Que o agente pode resolver casos reais (consultar, rastrear, agendar troca, abrir chamado) sem nunca acessar dados de outro cliente, **mesmo que o modelo tente**.
3. Que a passagem para um humano é parte do produto, e não um remendo: o atendente vê o que o agente fez e o bot sai de cena enquanto a pessoa atende.
4. Que dá para desenvolver e testar tudo isso **sem conta da Meta e sem conta da AWS**.

## Usuários

| Persona | Necessidade |
|---|---|
| Cliente da loja | Resolver dúvidas de pedido no WhatsApp a qualquer hora, sem menus |
| Atendente | Assumir conversas que o agente não resolve, com contexto completo |
| Time de tecnologia | Operar com custo baixo, rastrear falhas e evoluir as ferramentas sem mexer no agente |

## Escopo

**Dentro do escopo**

- Webhook da WhatsApp Cloud API (verificação do `GET` e assinatura `X-Hub-Signature-256`) como AWS Lambda atrás do API Gateway.
- Fila SQS com retentativa e DLQ, worker com idempotência pelo `message id` do WhatsApp.
- Agente com cinco ferramentas expostas por um servidor MCP: `consultar_pedido`, `rastrear_entrega`, `agendar_troca`, `abrir_chamado` e `transferir_para_humano`.
- Memória da conversa no MongoDB e mídias recebidas salvas no S3.
- Painel de atendimento com fila de transferências, histórico, ferramentas chamadas e resposta manual.
- Simulador de WhatsApp: uma Graph API falsa e um celular na tela, para rodar sem conta da Meta.
- LocalStack para rodar SQS, S3, Lambda e API Gateway localmente; Terraform para a AWS real.
- Evals com conversas roteirizadas.

**Fora do escopo (por enquanto)**

- Templates de mensagem (HSM) e janela de 24h da Meta.
- Transcrição de áudio.
- Autenticação no painel de atendimento.
- Deploy do worker e da API em ECS (o Terraform entrega a política IAM pronta para isso).

## Requisitos não funcionais

| Requisito | Como é atendido |
|---|---|
| Responder à Meta rapidamente | A Lambda só valida a assinatura e enfileira; o LLM roda fora do caminho do webhook |
| Não perder mensagens | SQS com visibilidade, retentativa com backoff e DLQ após 3 tentativas |
| Não responder duas vezes | Claim atômico por `message id` no MongoDB (índice único) |
| Privacidade entre clientes | O telefone é injetado pelo servidor nas ferramentas; o modelo nem vê esse parâmetro |
| Degradação elegante | Se o LLM ou o MCP caírem, o cliente recebe uma mensagem de contingência e a conversa vai para a fila humana |
| Reprodutibilidade | Tudo em containers, incluindo a "AWS" (LocalStack) e o "WhatsApp" (simulador) |

## Critérios de sucesso

- Uma mensagem assinada atravessa API Gateway → Lambda → SQS → worker → Graph API, e a resposta chega ao celular simulado.
- Assinatura forjada é recusada antes de entrar na fila.
- Com o LLM fora do ar, nenhum cliente fica sem resposta.
- Acurácia mínima de 75% nos evals com LLM real.
