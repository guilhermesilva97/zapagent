# ADR 0005: simulador de WhatsApp e LocalStack para rodar sem contas externas

**Status:** aceita

## Contexto

Para testar de verdade, o projeto depende de duas contas que quem avalia o repositório não tem: um app na Meta com número de WhatsApp Business e uma conta AWS. Sem elas, o projeto vira um código que ninguém consegue executar.

## Decisão

- **Graph API falsa** dentro da API, com as mesmas rotas e o mesmo formato da real (`POST /{version}/{phone_number_id}/messages`, `GET /{version}/{media_id}`), inclusive exigindo o token `Bearer`. O worker usa o **mesmo adaptador** para a Graph real e para a falsa; só muda `GRAPH_BASE_URL` e `GRAPH_TOKEN`.
- **Simulador de celular** no front, que monta o payload exatamente como a Meta envia, **assina com o app secret** e chama o webhook pelo API Gateway. A mensagem percorre o mesmo caminho de produção.
- **LocalStack 4.4** com S3, SQS, Lambda e API Gateway, provisionado por um container `bootstrap` idempotente (boto3), que também empacota a Lambda e popula o MongoDB.
- A versão do LocalStack é fixa (4.4), para o ambiente não mudar sozinho: a imagem `latest` muda de comportamento e de política de licenciamento entre versões.

## Consequências

- `docker compose up` sobe um ambiente completo, e o CI roda os mesmos testes de integração contra Lambda e SQS de verdade (do LocalStack).
- O LocalStack Community não tem API Gateway HTTP API (v2). Localmente uso REST API (v1) e, na AWS, HTTP API (v2). Por isso a Lambda aceita os dois formatos de evento, e isso tem teste.
- O LocalStack precisa do socket do Docker para criar o container da Lambda. Na primeira execução ele baixa a imagem de runtime Python, o que deixa o primeiro `up` mais lento.
- Ligar o WhatsApp real é configuração: `GRAPH_BASE_URL=https://graph.facebook.com`, token e `PHONE_NUMBER_ID` do app, e a URL do API Gateway da AWS cadastrada como webhook na Meta.
