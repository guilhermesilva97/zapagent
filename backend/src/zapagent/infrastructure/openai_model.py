import json
from collections.abc import Sequence
from typing import Any

from openai import AsyncOpenAI

from zapagent.domain.llm import Message, ModelTurn, ToolCall, ToolSpec


class OpenAICompatibleModel:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._options: dict[str, Any] = {}
        if temperature is not None:
            self._options["temperature"] = temperature
        if reasoning_effort:
            self._options["reasoning_effort"] = reasoning_effort

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelTurn:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_openai_message(message) for message in messages],
            tools=[_to_openai_tool(tool) for tool in tools],
            **self._options,
        )
        message = response.choices[0].message
        calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments),
            )
            for call in message.tool_calls or ()
        )
        return ModelTurn(text=message.content, tool_calls=calls)


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _to_openai_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
