import pytest

from tests.fakes import PHONE, FakeWhatsApp, MemoryConversations, MemoryEvents, MemoryLog
from zapagent.application.attendant import AttendantDesk, ConversationNotFound
from zapagent.domain.conversation import Conversation, ConversationStatus, InvalidTransition
from zapagent.domain.handoff import RELEASE_MESSAGE, wants_human


@pytest.mark.parametrize(
    "text",
    [
        "quero falar com um atendente",
        "Me passa pra um HUMANO",
        "preciso falar com alguém",
        "não quero falar com robô",
    ],
)
def test_detects_explicit_requests_for_a_human(text: str) -> None:
    assert wants_human(text)


@pytest.mark.parametrize(
    "text", ["qual o status do meu pedido?", "humanidade", "quero trocar o tênis", ""]
)
def test_ignores_regular_messages(text: str) -> None:
    assert not wants_human(text)


def test_conversation_lifecycle() -> None:
    conversation = Conversation(phone=PHONE)
    conversation.request_human("motivo")
    assert conversation.status == ConversationStatus.WAITING_HUMAN

    conversation.assume("Rita")
    assert conversation.status == ConversationStatus.HUMAN
    with pytest.raises(InvalidTransition):
        conversation.assume("Paulo")

    conversation.request_human("de novo")
    assert conversation.status == ConversationStatus.HUMAN

    conversation.release()
    assert conversation.bot_active
    assert conversation.attendant is None
    with pytest.raises(InvalidTransition):
        conversation.release()


@pytest.mark.anyio
async def test_attendant_desk_assume_reply_and_release() -> None:
    conversations = MemoryConversations({PHONE: Conversation(phone=PHONE)})
    whatsapp = FakeWhatsApp()
    events = MemoryEvents()
    log = MemoryLog()
    desk = AttendantDesk(conversations, log, events, whatsapp)

    await desk.assume(PHONE, "Rita")
    entry = await desk.reply(PHONE, "Rita", "Olá, sou a Rita!")
    await desk.release(PHONE)

    assert entry.author == "attendant"
    assert whatsapp.sent == [(PHONE, "Olá, sou a Rita!"), (PHONE, RELEASE_MESSAGE)]
    assert conversations.items[PHONE].bot_active
    assert events.types().count("status_changed") == 2

    with pytest.raises(ConversationNotFound):
        await desk.assume("000", "Rita")
