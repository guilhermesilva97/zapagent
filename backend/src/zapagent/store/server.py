from typing import Any

from mcp.server.fastmcp import FastMCP

from zapagent.store.service import StoreService

INSTRUCTIONS = (
    "Sistema de atendimento da Loja Aurora. Todas as ferramentas recebem o telefone do cliente "
    "no formato internacional sem símbolos e só retornam dados que pertencem a esse telefone."
)


def build_store_server(service: StoreService, host: str, port: int) -> FastMCP:
    server = FastMCP("zapagent-store", instructions=INSTRUCTIONS, host=host, port=port)

    @server.tool(
        name="consultar_pedido",
        description="Consulta status, itens, valor e previsão de entrega de um pedido do cliente.",
    )
    async def consultar_pedido(telefone: str, numero_pedido: str) -> dict[str, Any]:
        return await service.order_summary(telefone, numero_pedido)

    @server.tool(
        name="rastrear_entrega",
        description="Retorna transportadora, código de rastreio e eventos da entrega de um pedido.",
    )
    async def rastrear_entrega(telefone: str, numero_pedido: str) -> dict[str, Any]:
        return await service.tracking(telefone, numero_pedido)

    @server.tool(
        name="agendar_troca",
        description=(
            "Agenda a coleta para troca de um pedido entregue há no máximo 30 dias. "
            "data_coleta no formato AAAA-MM-DD, a partir de amanhã, exceto domingo."
        ),
    )
    async def agendar_troca(
        telefone: str, numero_pedido: str, motivo: str, data_coleta: str
    ) -> dict[str, Any]:
        return await service.schedule_exchange(telefone, numero_pedido, motivo, data_coleta)

    @server.tool(
        name="abrir_chamado",
        description="Abre um chamado de suporte para problemas que não são troca nem rastreio.",
    )
    async def abrir_chamado(telefone: str, assunto: str, descricao: str) -> dict[str, Any]:
        return await service.open_ticket(telefone, assunto, descricao)

    @server.tool(
        name="transferir_para_humano",
        description=(
            "Transfere a conversa para um atendente humano e registra um protocolo. "
            "Informe o motivo da transferência."
        ),
    )
    async def transferir_para_humano(telefone: str, motivo: str) -> dict[str, Any]:
        return await service.request_human(telefone, motivo)

    return server
