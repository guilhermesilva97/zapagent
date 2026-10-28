# ADR 0002: idempotência no consumidor com claim no MongoDB

**Status:** aceita

## Contexto

Mensagens podem chegar repetidas por três caminhos: reenvio da Meta, entrega duplicada do SQS (*at-least-once*) e retentativa depois de uma falha no meio do processamento. Responder duas vezes ao cliente é visível e constrangedor.

## Decisão

- Antes de processar, o worker faz um **claim**: `insert_one({"_id": message_id})` numa coleção com índice único (o próprio `_id`). Se der `DuplicateKeyError`, a mensagem já foi tratada e é descartada.
- Se o processamento falhar por infraestrutura, o worker **libera o claim** e não apaga a mensagem da fila. A próxima tentativa consegue processá-la.
- O histórico usa *upsert* por `message_id`, para uma retentativa não duplicar a mensagem do cliente no painel.
- Os claims expiram em 7 dias por índice TTL.

## Consequências

- Uma mensagem nunca gera duas respostas, mesmo com dois workers concorrentes.
- Se o worker morrer depois do claim e antes de responder (sem chegar a liberar), a mensagem fica marcada como processada sem resposta. Aceitei esse risco: é raro, e a alternativa (marcar como processada só no fim) abre a porta para respostas duplicadas, que são piores. A evolução natural é gravar o status do claim (`processing`/`done`) com prazo de expiração.

## Alternativas consideradas

- **Verificar "já respondi?" no histórico:** tem condição de corrida entre dois workers.
- **Deduplicação do SQS FIFO:** janela de 5 minutos, insuficiente para reenvios da Meta.
