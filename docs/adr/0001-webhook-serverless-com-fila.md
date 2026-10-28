# ADR 0001: webhook em Lambda que só valida e enfileira

**Status:** aceita

## Contexto

A Meta espera resposta rápida do webhook e reenvia a notificação quando não recebe `200`. Uma resposta do agente pode levar de 3 a 30 segundos (várias chamadas ao LLM e às ferramentas). Se o webhook processar tudo na mesma requisição, timeouts geram reenvios, que geram respostas duplicadas.

## Decisão

- O webhook é uma **AWS Lambda** atrás do API Gateway. Ela faz só três coisas: responde à verificação `GET`, valida a assinatura `X-Hub-Signature-256` e publica cada mensagem normalizada no **SQS**.
- O código da Lambda usa apenas a biblioteca padrão e o `boto3` que já vem no runtime. O pacote tem poucos KB e não precisa de *layer*.
- O processamento pesado fica num **worker** que consome a fila com long polling.

## Consequências

**Positivas**

- O webhook responde em milissegundos, independentemente do LLM.
- Picos de mensagens viram fila, não erro. O worker escala pelo tamanho da fila.
- Custo próximo de zero quando não há tráfego.
- A fila dá retentativa e DLQ de graça.

**Negativas**

- A entrega passa a ser *at-least-once*: a mesma mensagem pode chegar duas vezes ao worker. Isso exigiu a [ADR 0002](0002-idempotencia-no-consumidor.md).
- Mais peças para operar (API Gateway, Lambda, fila). O Terraform e o LocalStack reduzem esse custo.

## Alternativas consideradas

- **Webhook direto na API FastAPI:** simples, mas acopla disponibilidade e latência do webhook ao agente.
- **Fila FIFO com deduplicação:** o SQS deduplica apenas numa janela de 5 minutos, e a Meta pode reenviar depois disso. A idempotência no consumidor continuaria necessária.
