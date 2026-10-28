# ADR 0004: handoff humano como máquina de estados da conversa

**Status:** aceita

## Contexto

O agente vai errar ou travar em algum momento, e o cliente às vezes simplesmente quer falar com uma pessoa. O erro mais comum nesses sistemas é o bot continuar respondendo enquanto o atendente conversa, ou nunca devolver a conversa.

## Decisão

- A conversa tem três estados: `bot`, `waiting_human` e `human`. As transições ficam na entidade `Conversation`, que recusa as inválidas (por exemplo, um segundo atendente assumindo uma conversa que já tem dono).
- Quatro gatilhos levam para `waiting_human`:
  1. o cliente pede explicitamente (regra determinística por expressão regular, **antes** de chamar o LLM);
  2. o agente chama `transferir_para_humano`;
  3. o LLM ou o MCP falham;
  4. o agente estoura o limite de passos.
- Fora do estado `bot`, o worker registra a mensagem e publica o evento para o painel, mas **não chama o agente**.
- Ao devolver, o atendente dispara uma mensagem de encerramento e o bot volta a responder.
- A transferência pela ferramenta também gera um protocolo no sistema da loja (`AT-...`), separado do estado da conversa: o MCP cuida da loja, o worker cuida da conversa.

## Consequências

- O pedido explícito de atendente é atendido mesmo com o LLM fora do ar, e sem gastar tokens.
- O painel sempre mostra por que a conversa foi transferida (`handoff_reason`).
- Falha do LLM vira experiência degradada, não silêncio.
