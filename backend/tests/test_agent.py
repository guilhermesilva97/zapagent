import pytest

from tests.fakes import PHONE, FakeGateway, MemoryEvents, ScriptedModel, call
from zapagent.application.agent import RunAgent
from zapagent.domain.conversation import ChatEntry, Conversation
from zapagent.domain.handoff import HANDOFF_BY_LIMIT, HANDOFF_MESSAGE
from zapagent.domain.llm import ModelTurn, ToolOutcome

pytestmark = pytest.mark.anyio


def history(text: str = "Qual o status do pedido 1001?") -> list[ChatEntry]:
    return [ChatEntry(phone=PHONE, direction="in", author="customer", text=text)]


async def test_injects_customer_phone_and_hides_it_from_the_model() -> None:
    gateway = FakeGateway()
    events = MemoryEvents()
    model = ScriptedModel(
        [
            ModelTurn(None, (call("consultar_pedido", numero_pedido="1001", telefone="999"),)),
            ModelTurn("Seu pedido 1001 foi entregue.", ()),
        ]
    )
    agent = RunAgent(model, gateway.factory(), events)

    outcome = await agent.run(Conversation(phone=PHONE, name="Ana"), history())

    assert outcome.reply == "Seu pedido 1001 foi entregue."
    assert outcome.handoff_reason is None
    assert gateway.calls == [("consultar_pedido", {"numero_pedido": "1001", "telefone": PHONE})]
    schema = model.tools_seen[0][0].parameters
    assert "telefone" not in schema["properties"]
    assert schema["required"] == ["numero_pedido"]
    assert events.types() == ["tool_started", "tool_finished"]


async def test_transfer_tool_ends_with_handoff() -> None:
    gateway = FakeGateway()
    model = ScriptedModel(
        [ModelTurn(None, (call("transferir_para_humano", motivo="cliente irritado"),))]
    )
    agent = RunAgent(model, gateway.factory(), MemoryEvents())

    outcome = await agent.run(Conversation(phone=PHONE), history("isso é um absurdo"))

    assert outcome.handoff_reason == "cliente irritado"
    assert outcome.protocol == "AT-1"
    assert outcome.reply == HANDOFF_MESSAGE


async def test_tool_errors_go_back_to_the_model() -> None:
    gateway = FakeGateway()
    gateway.responses["consultar_pedido"] = ToolOutcome(False, "Não encontrei o pedido 9")
    model = ScriptedModel(
        [
            ModelTurn(None, (call("consultar_pedido", numero_pedido="9"),)),
            ModelTurn("Não achei esse pedido, pode conferir o número?", ()),
        ]
    )
    agent = RunAgent(model, gateway.factory(), MemoryEvents())

    outcome = await agent.run(Conversation(phone=PHONE), history())

    tool_message = model.received[1][-1]
    assert tool_message.role == "tool"
    assert tool_message.content == "ERRO: Não encontrei o pedido 9"
    assert outcome.reply.startswith("Não achei")


async def test_hands_off_when_step_limit_is_reached() -> None:
    model = ScriptedModel(
        [ModelTurn(None, (call("consultar_pedido", numero_pedido="1"),)) for _ in range(2)]
    )
    agent = RunAgent(model, FakeGateway().factory(), MemoryEvents(), max_steps=2)

    outcome = await agent.run(Conversation(phone=PHONE), history())

    assert outcome.handoff_reason == HANDOFF_BY_LIMIT


async def test_history_becomes_chat_messages() -> None:
    model = ScriptedModel([ModelTurn("Oi!", ())])
    agent = RunAgent(model, FakeGateway().factory(), MemoryEvents(), store_name="Loja Teste")
    entries = [
        ChatEntry(phone=PHONE, direction="in", author="customer", text="oi"),
        ChatEntry(phone=PHONE, direction="out", author="attendant", text="olá", attendant="Rita"),
        ChatEntry(phone=PHONE, direction="in", author="customer", text="", media_key="s3://b/k"),
    ]

    await agent.run(Conversation(phone=PHONE, name="Ana"), entries)

    messages = model.received[0]
    assert "Loja Teste" in messages[0].content
    assert "Ana" in messages[0].content
    assert [m.role for m in messages[1:]] == ["user", "assistant", "user"]
    assert messages[2].content == "[atendente Rita] olá"
    assert "s3://b/k" in messages[3].content
