import logging
from enum import StrEnum

from zapagent.application.agent import AgentOutcome, RunAgent
from zapagent.application.ports import (
    ConversationRepository,
    EventPublisher,
    IdempotencyStore,
    MediaDownloader,
    MediaStorage,
    MessageLog,
    MessageSender,
)
from zapagent.domain.conversation import ChatEntry, Conversation, Event, InboundMessage
from zapagent.domain.handoff import (
    FALLBACK_MESSAGE,
    HANDOFF_BY_CUSTOMER,
    HANDOFF_BY_FAILURE,
    HANDOFF_MESSAGE,
    wants_human,
)

logger = logging.getLogger("zapagent.inbound")


class InboundResult(StrEnum):
    DUPLICATE = "duplicate"
    WAITING_HUMAN = "waiting_human"
    HANDED_OFF = "handed_off"
    ANSWERED = "answered"
    SILENT = "silent"


class ProcessInboundMessage:
    def __init__(
        self,
        conversations: ConversationRepository,
        log: MessageLog,
        idempotency: IdempotencyStore,
        events: EventPublisher,
        sender: MessageSender,
        downloader: MediaDownloader,
        storage: MediaStorage,
        agent: RunAgent,
        history_limit: int = 20,
    ) -> None:
        self._conversations = conversations
        self._log = log
        self._idempotency = idempotency
        self._events = events
        self._sender = sender
        self._downloader = downloader
        self._storage = storage
        self._agent = agent
        self._history_limit = history_limit

    async def execute(self, message: InboundMessage) -> InboundResult:
        if not await self._idempotency.claim(message.message_id):
            logger.info("Mensagem %s já processada; ignorando", message.message_id)
            return InboundResult.DUPLICATE
        try:
            return await self._handle(message)
        except Exception:
            await self._idempotency.release(message.message_id)
            raise

    async def _handle(self, message: InboundMessage) -> InboundResult:
        conversation = await self._conversations.get_or_create(message.phone, message.name)
        media_key = await self._store_media(message)
        entry = ChatEntry(
            phone=message.phone,
            direction="in",
            author="customer",
            text=message.text or ("[mídia]" if media_key else ""),
            message_id=message.message_id,
            media_key=media_key,
        )
        await self._log.append(entry)
        await self._events.publish(Event("message_received", message.phone, entry.to_dict()))

        if not conversation.bot_active:
            return InboundResult.WAITING_HUMAN

        if wants_human(message.text):
            await self._hand_off(conversation, HANDOFF_BY_CUSTOMER)
            await self._reply(conversation, HANDOFF_MESSAGE)
            return InboundResult.HANDED_OFF

        history = await self._log.recent(message.phone, self._history_limit)
        try:
            outcome = await self._agent.run(conversation, history)
        except Exception:
            logger.exception("Falha no agente para %s", message.phone)
            outcome = AgentOutcome(reply=FALLBACK_MESSAGE, handoff_reason=HANDOFF_BY_FAILURE)

        if outcome.handoff_reason:
            await self._hand_off(conversation, outcome.handoff_reason)
        if outcome.reply:
            await self._reply(conversation, outcome.reply)
        if outcome.handoff_reason:
            return InboundResult.HANDED_OFF
        return InboundResult.ANSWERED if outcome.reply else InboundResult.SILENT

    async def _store_media(self, message: InboundMessage) -> str | None:
        if not message.has_media:
            return None
        content, mime_type = await self._downloader.download(message.media_id or "")
        key = f"{message.phone}/{message.message_id}"
        return await self._storage.store(key, content, message.mime_type or mime_type)

    async def _hand_off(self, conversation: Conversation, reason: str) -> None:
        conversation.request_human(reason)
        await self._conversations.save(conversation)
        await self._events.publish(
            Event(
                "status_changed",
                conversation.phone,
                {"status": conversation.status.value, "reason": reason},
            )
        )

    async def _reply(self, conversation: Conversation, text: str) -> None:
        message_id = await self._sender.send_text(conversation.phone, text)
        entry = ChatEntry(
            phone=conversation.phone,
            direction="out",
            author="bot",
            text=text,
            message_id=message_id,
        )
        await self._log.append(entry)
        await self._events.publish(Event("message_sent", conversation.phone, entry.to_dict()))
