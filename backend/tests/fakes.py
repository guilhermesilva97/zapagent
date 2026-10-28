from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from zapagent.domain.conversation import ChatEntry, Conversation, Event
from zapagent.domain.llm import Message, ModelTurn, ToolCall, ToolOutcome, ToolSpec

PHONE = "5511999990001"


def call(name: str, call_id: str = "c1", **arguments: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


@dataclass
class ScriptedModel:
    turns: list[ModelTurn]
    received: list[list[Message]] = field(default_factory=list)
    tools_seen: list[list[ToolSpec]] = field(default_factory=list)

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelTurn:
        self.received.append(list(messages))
        self.tools_seen.append(list(tools))
        return self.turns.pop(0)


class BrokenModel:
    async def complete(self, messages, tools):
        raise ConnectionError("llm offline")


TOOL_SCHEMA = {
    "type": "object",
    "properties": {"telefone": {"type": "string"}, "numero_pedido": {"type": "string"}},
    "required": ["telefone", "numero_pedido"],
}


@dataclass
class FakeGateway:
    responses: dict[str, ToolOutcome] = field(
        default_factory=lambda: {
            "consultar_pedido": ToolOutcome(True, {"numero_pedido": "1001", "status": "entregue"}),
            "transferir_para_humano": ToolOutcome(
                True, {"protocolo": "AT-1", "status": "aberto", "handoff": True}
            ),
        }
    )
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name, "", TOOL_SCHEMA) for name in self.responses]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return self.responses[name]

    def factory(self):
        @asynccontextmanager
        async def open_gateway() -> AsyncIterator["FakeGateway"]:
            yield self

        return open_gateway


@dataclass
class MemoryEvents:
    published: list[Event] = field(default_factory=list)

    async def publish(self, event: Event) -> None:
        self.published.append(event)

    def types(self) -> list[str]:
        return [event.type for event in self.published]


@dataclass
class MemoryConversations:
    items: dict[str, Conversation] = field(default_factory=dict)

    async def get(self, phone: str) -> Conversation | None:
        return self.items.get(phone)

    async def get_or_create(self, phone: str, name: str) -> Conversation:
        return self.items.setdefault(phone, Conversation(phone=phone, name=name))

    async def save(self, conversation: Conversation) -> None:
        self.items[conversation.phone] = conversation


@dataclass
class MemoryLog:
    entries: list[ChatEntry] = field(default_factory=list)

    async def append(self, entry: ChatEntry) -> None:
        self.entries.append(entry)

    async def recent(self, phone: str, limit: int) -> list[ChatEntry]:
        return [entry for entry in self.entries if entry.phone == phone][-limit:]


@dataclass
class MemoryIdempotency:
    claimed: set[str] = field(default_factory=set)

    async def claim(self, message_id: str) -> bool:
        if message_id in self.claimed:
            return False
        self.claimed.add(message_id)
        return True

    async def release(self, message_id: str) -> None:
        self.claimed.discard(message_id)


@dataclass
class FakeWhatsApp:
    sent: list[tuple[str, str]] = field(default_factory=list)
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    fail_send: bool = False

    async def send_text(self, phone: str, text: str) -> str:
        if self.fail_send:
            raise RuntimeError("graph fora do ar")
        self.sent.append((phone, text))
        return f"wamid.OUT{len(self.sent)}"

    async def download(self, media_id: str) -> tuple[bytes, str]:
        return self.media[media_id]


@dataclass
class MemoryStorage:
    objects: dict[str, bytes] = field(default_factory=dict)

    async def store(self, key: str, content: bytes, mime_type: str) -> str:
        self.objects[key] = content
        return f"s3://test/{key}"
