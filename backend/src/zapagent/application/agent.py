import copy
import json
from dataclasses import dataclass
from typing import Any

from zapagent.application.ports import EventPublisher, LanguageModel, ToolGatewayFactory
from zapagent.domain.conversation import ChatEntry, Conversation, Event
from zapagent.domain.handoff import HANDOFF_BY_LIMIT, HANDOFF_MESSAGE
from zapagent.domain.llm import Message, ToolSpec

IDENTITY_ARGUMENT = "telefone"
HANDOFF_TOOL = "transferir_para_humano"

SYSTEM_PROMPT = """Você é a Aurora, assistente virtual da {store} no WhatsApp.

Regras:
1. Use as ferramentas para qualquer informação sobre pedidos, entregas, trocas e chamados. \
Nunca invente status, datas, valores ou protocolos.
2. Se o cliente não informou o número do pedido, peça antes de consultar.
3. Para agendar troca você precisa do número do pedido, do motivo e da data de coleta \
(formato AAAA-MM-DD). Se o cliente já informou tudo, agende direto.
4. Quando uma ferramenta recusar a solicitação, explique ao cliente o motivo da recusa \
com as informações que ela devolveu (prazos, regras) e não transfira nessa mesma resposta.
5. Chame transferir_para_humano quando o cliente estiver irritado, quando o pedido fugir \
do que as ferramentas resolvem ou quando o cliente insistir depois de uma recusa.
6. Responda em português do Brasil, em mensagens curtas próprias de WhatsApp, sem markdown.

Cliente: {name}"""


@dataclass(frozen=True)
class AgentOutcome:
    reply: str | None
    handoff_reason: str | None = None
    protocol: str | None = None


class RunAgent:
    def __init__(
        self,
        model: LanguageModel,
        gateway_factory: ToolGatewayFactory,
        events: EventPublisher,
        store_name: str = "Loja Aurora",
        max_steps: int = 6,
    ) -> None:
        self._model = model
        self._gateway_factory = gateway_factory
        self._events = events
        self._store_name = store_name
        self._max_steps = max_steps

    async def run(self, conversation: Conversation, history: list[ChatEntry]) -> AgentOutcome:
        async with self._gateway_factory() as gateway:
            tools = [_hide_identity(tool) for tool in await gateway.list_tools()]
            messages = [
                Message.system(
                    SYSTEM_PROMPT.format(store=self._store_name, name=conversation.name or "?")
                ),
                *[_to_message(entry) for entry in history],
            ]

            for _ in range(self._max_steps):
                turn = await self._model.complete(messages, tools)
                messages.append(Message.assistant(turn))
                if not turn.tool_calls:
                    return AgentOutcome(reply=(turn.text or "").strip() or None)

                for call in turn.tool_calls:
                    arguments = {**call.arguments, IDENTITY_ARGUMENT: conversation.phone}
                    await self._publish("tool_started", conversation, call.id, call.name, arguments)
                    outcome = await gateway.call(call.name, arguments)
                    await self._publish(
                        "tool_finished",
                        conversation,
                        call.id,
                        call.name,
                        arguments,
                        ok=outcome.ok,
                        result=outcome.content,
                    )
                    if call.name == HANDOFF_TOOL and outcome.ok:
                        content = outcome.content if isinstance(outcome.content, dict) else {}
                        return AgentOutcome(
                            reply=HANDOFF_MESSAGE,
                            handoff_reason=str(call.arguments.get("motivo") or "transferido"),
                            protocol=content.get("protocolo"),
                        )
                    messages.append(Message.tool(call.id, _for_model(outcome.ok, outcome.content)))

        return AgentOutcome(reply=HANDOFF_MESSAGE, handoff_reason=HANDOFF_BY_LIMIT)

    async def _publish(
        self,
        kind: str,
        conversation: Conversation,
        call_id: str,
        tool: str,
        arguments: dict[str, Any],
        **extra: Any,
    ) -> None:
        data = {"call_id": call_id, "tool": tool, "arguments": arguments, **extra}
        await self._events.publish(Event(kind, conversation.phone, data))


def _hide_identity(tool: ToolSpec) -> ToolSpec:
    schema = copy.deepcopy(tool.parameters)
    schema.get("properties", {}).pop(IDENTITY_ARGUMENT, None)
    if IDENTITY_ARGUMENT in schema.get("required", []):
        schema["required"] = [name for name in schema["required"] if name != IDENTITY_ARGUMENT]
    return ToolSpec(tool.name, tool.description, schema)


def _to_message(entry: ChatEntry) -> Message:
    if entry.author == "customer":
        text = entry.text or ""
        if entry.media_key:
            text = f"{text}\n[o cliente enviou um arquivo: {entry.media_key}]".strip()
        return Message.user(text)
    if entry.author == "attendant":
        return Message.assistant_text(f"[atendente {entry.attendant}] {entry.text}")
    return Message.assistant_text(entry.text)


def _for_model(ok: bool, content: Any) -> str:
    if not ok:
        return f"ERRO: {content}"
    return json.dumps(content, ensure_ascii=False, default=str)
