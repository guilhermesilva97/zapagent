from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    content: Any


@dataclass(frozen=True)
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls("system", content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls("user", content)

    @classmethod
    def assistant_text(cls, content: str) -> "Message":
        return cls("assistant", content)

    @classmethod
    def assistant(cls, turn: ModelTurn) -> "Message":
        return cls("assistant", turn.text, turn.tool_calls)

    @classmethod
    def tool(cls, call_id: str, content: str) -> "Message":
        return cls("tool", content, tool_call_id=call_id)
