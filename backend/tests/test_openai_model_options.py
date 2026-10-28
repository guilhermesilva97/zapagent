from types import SimpleNamespace

import pytest

from zapagent.infrastructure.openai_model import OpenAICompatibleModel


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordingCompletions:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def model_with(completions: RecordingCompletions, **options) -> OpenAICompatibleModel:
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatibleModel(client, "gpt-5.6-luna", **options)


@pytest.mark.anyio
async def test_omits_optional_parameters_by_default() -> None:
    completions = RecordingCompletions()

    await model_with(completions).complete([], [])

    assert "temperature" not in completions.kwargs
    assert "reasoning_effort" not in completions.kwargs


@pytest.mark.anyio
async def test_sends_temperature_and_reasoning_effort_when_configured() -> None:
    completions = RecordingCompletions()

    await model_with(completions, temperature=0, reasoning_effort="none").complete([], [])

    assert completions.kwargs["temperature"] == 0
    assert completions.kwargs["reasoning_effort"] == "none"
