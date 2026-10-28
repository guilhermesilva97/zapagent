from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from zapagent.domain.conversation import ChatEntry, Conversation, Event
from zapagent.domain.llm import Message, ModelTurn, ToolOutcome, ToolSpec


class LanguageModel(Protocol):
    async def complete(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelTurn: ...


class ToolGateway(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


class ToolGatewayFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[ToolGateway]: ...


class ConversationRepository(Protocol):
    async def get(self, phone: str) -> Conversation | None: ...

    async def get_or_create(self, phone: str, name: str) -> Conversation: ...

    async def save(self, conversation: Conversation) -> None: ...


class MessageLog(Protocol):
    async def append(self, entry: ChatEntry) -> None: ...

    async def recent(self, phone: str, limit: int) -> list[ChatEntry]: ...


class IdempotencyStore(Protocol):
    async def claim(self, message_id: str) -> bool: ...

    async def release(self, message_id: str) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: Event) -> None: ...


class MessageSender(Protocol):
    async def send_text(self, phone: str, text: str) -> str: ...


class MediaDownloader(Protocol):
    async def download(self, media_id: str) -> tuple[bytes, str]: ...


class MediaStorage(Protocol):
    async def store(self, key: str, content: bytes, mime_type: str) -> str: ...
