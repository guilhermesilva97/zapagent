from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


def now() -> datetime:
    return datetime.now(UTC)


class ConversationStatus(StrEnum):
    BOT = "bot"
    WAITING_HUMAN = "waiting_human"
    HUMAN = "human"


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    phone: str
    name: str
    type: str
    text: str
    timestamp: int
    phone_number_id: str
    media_id: str | None = None
    mime_type: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InboundMessage":
        return cls(
            message_id=str(data["message_id"]),
            phone=str(data["phone"]),
            name=str(data.get("name") or ""),
            type=str(data.get("type") or "text"),
            text=str(data.get("text") or ""),
            timestamp=int(data.get("timestamp") or 0),
            phone_number_id=str(data.get("phone_number_id") or ""),
            media_id=data.get("media_id"),
            mime_type=data.get("mime_type"),
        )

    @property
    def has_media(self) -> bool:
        return bool(self.media_id)


@dataclass
class Conversation:
    phone: str
    name: str = ""
    status: ConversationStatus = ConversationStatus.BOT
    handoff_reason: str | None = None
    attendant: str | None = None
    updated_at: datetime = field(default_factory=now)

    @property
    def bot_active(self) -> bool:
        return self.status == ConversationStatus.BOT

    def request_human(self, reason: str) -> None:
        if self.status == ConversationStatus.HUMAN:
            return
        self.status = ConversationStatus.WAITING_HUMAN
        self.handoff_reason = reason
        self.updated_at = now()

    def assume(self, attendant: str) -> None:
        if not attendant.strip():
            raise InvalidTransition("Informe o nome do atendente.")
        if self.status == ConversationStatus.HUMAN and self.attendant != attendant:
            raise InvalidTransition(f"A conversa já está com {self.attendant}.")
        self.status = ConversationStatus.HUMAN
        self.attendant = attendant
        self.updated_at = now()

    def release(self) -> None:
        if self.status == ConversationStatus.BOT:
            raise InvalidTransition("A conversa já está com o assistente.")
        self.status = ConversationStatus.BOT
        self.attendant = None
        self.handoff_reason = None
        self.updated_at = now()


Direction = Literal["in", "out"]
Author = Literal["customer", "bot", "attendant", "system"]


@dataclass(frozen=True)
class ChatEntry:
    phone: str
    direction: Direction
    author: Author
    text: str
    at: datetime = field(default_factory=now)
    message_id: str | None = None
    media_key: str | None = None
    attendant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["at"] = self.at.isoformat()
        return data


@dataclass(frozen=True)
class Event:
    type: str
    phone: str
    data: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=now)
