import pytest

from tests.fakes import (
    PHONE,
    BrokenModel,
    FakeGateway,
    FakeWhatsApp,
    MemoryConversations,
    MemoryEvents,
    MemoryIdempotency,
    MemoryLog,
    MemoryStorage,
    ScriptedModel,
)
from zapagent.application.agent import RunAgent
from zapagent.application.process_inbound import InboundResult, ProcessInboundMessage
from zapagent.domain.conversation import ConversationStatus, InboundMessage
from zapagent.domain.handoff import (
    FALLBACK_MESSAGE,
    HANDOFF_BY_CUSTOMER,
    HANDOFF_BY_FAILURE,
    HANDOFF_MESSAGE,
)
from zapagent.domain.llm import ModelTurn

pytestmark = pytest.mark.anyio


def inbound(text: str = "Oi", message_id: str = "wamid.1", **extra) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        phone=PHONE,
        name="Ana",
        type="text",
        text=text,
        timestamp=0,
        phone_number_id="PNID",
        **extra,
    )


class World:
    def __init__(self, model=None) -> None:
        self.conversations = MemoryConversations()
        self.log = MemoryLog()
        self.idempotency = MemoryIdempotency()
        self.events = MemoryEvents()
        self.whatsapp = FakeWhatsApp()
        self.storage = MemoryStorage()
        self.model = model or ScriptedModel([ModelTurn("Olá! Como posso ajudar?", ())])
        self.use_case = ProcessInboundMessage(
            conversations=self.conversations,
            log=self.log,
            idempotency=self.idempotency,
            events=self.events,
            sender=self.whatsapp,
            downloader=self.whatsapp,
            storage=self.storage,
            agent=RunAgent(self.model, FakeGateway().factory(), self.events),
        )

    def status(self) -> ConversationStatus:
        return self.conversations.items[PHONE].status


async def test_answers_with_the_agent() -> None:
    world = World()

    result = await world.use_case.execute(inbound())

    assert result == InboundResult.ANSWERED
    assert world.whatsapp.sent == [(PHONE, "Olá! Como posso ajudar?")]
    assert [entry.author for entry in world.log.entries] == ["customer", "bot"]
    assert world.events.types() == ["message_received", "message_sent"]


async def test_duplicate_webhook_delivery_is_processed_once() -> None:
    world = World()

    first = await world.use_case.execute(inbound())
    second = await world.use_case.execute(inbound())

    assert (first, second) == (InboundResult.ANSWERED, InboundResult.DUPLICATE)
    assert len(world.whatsapp.sent) == 1


async def test_infrastructure_failure_releases_the_claim_for_retry() -> None:
    world = World(ScriptedModel([ModelTurn("Oi", ()), ModelTurn("Oi de novo", ())]))
    world.whatsapp.fail_send = True

    with pytest.raises(RuntimeError):
        await world.use_case.execute(inbound())

    world.whatsapp.fail_send = False
    assert await world.use_case.execute(inbound()) == InboundResult.ANSWERED


async def test_customer_asking_for_human_skips_the_llm() -> None:
    world = World(ScriptedModel([]))

    result = await world.use_case.execute(inbound("Quero falar com um atendente"))

    assert result == InboundResult.HANDED_OFF
    assert world.status() == ConversationStatus.WAITING_HUMAN
    assert world.conversations.items[PHONE].handoff_reason == HANDOFF_BY_CUSTOMER
    assert world.whatsapp.sent[-1][1] == HANDOFF_MESSAGE
    assert world.model.received == []


async def test_bot_stays_silent_while_a_human_owns_the_conversation() -> None:
    world = World(ScriptedModel([]))
    await world.use_case.execute(inbound("atendente por favor", "wamid.1"))
    world.conversations.items[PHONE].assume("Rita")

    result = await world.use_case.execute(inbound("ainda está aí?", "wamid.2"))

    assert result == InboundResult.WAITING_HUMAN
    assert len(world.whatsapp.sent) == 1
    assert world.log.entries[-1].text == "ainda está aí?"


async def test_llm_failure_sends_fallback_and_hands_off() -> None:
    world = World(BrokenModel())

    result = await world.use_case.execute(inbound("Qual o status do pedido 1001?"))

    assert result == InboundResult.HANDED_OFF
    assert world.whatsapp.sent == [(PHONE, FALLBACK_MESSAGE)]
    assert world.conversations.items[PHONE].handoff_reason == HANDOFF_BY_FAILURE
    assert "status_changed" in world.events.types()


async def test_media_is_downloaded_and_stored() -> None:
    world = World()
    world.whatsapp.media["M1"] = (b"jpeg-bytes", "image/jpeg")

    await world.use_case.execute(
        inbound("produto chegou quebrado", media_id="M1", mime_type="image/jpeg")
    )

    assert world.storage.objects == {f"{PHONE}/wamid.1": b"jpeg-bytes"}
    assert world.log.entries[0].media_key == f"s3://test/{PHONE}/wamid.1"
