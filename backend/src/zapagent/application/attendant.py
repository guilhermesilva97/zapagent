from zapagent.application.ports import (
    ConversationRepository,
    EventPublisher,
    MessageLog,
    MessageSender,
)
from zapagent.domain.conversation import ChatEntry, Conversation, Event
from zapagent.domain.handoff import RELEASE_MESSAGE


class ConversationNotFound(Exception):
    pass


class AttendantDesk:
    def __init__(
        self,
        conversations: ConversationRepository,
        log: MessageLog,
        events: EventPublisher,
        sender: MessageSender,
    ) -> None:
        self._conversations = conversations
        self._log = log
        self._events = events
        self._sender = sender

    async def assume(self, phone: str, attendant: str) -> Conversation:
        conversation = await self._load(phone)
        conversation.assume(attendant)
        await self._save(conversation)
        return conversation

    async def release(self, phone: str) -> Conversation:
        conversation = await self._load(phone)
        conversation.release()
        await self._save(conversation)
        await self._send(conversation, RELEASE_MESSAGE, author="bot", attendant=None)
        return conversation

    async def reply(self, phone: str, attendant: str, text: str) -> ChatEntry:
        conversation = await self._load(phone)
        if not conversation.bot_active and conversation.attendant != attendant:
            conversation.assume(attendant)
            await self._save(conversation)
        return await self._send(conversation, text, author="attendant", attendant=attendant)

    async def _load(self, phone: str) -> Conversation:
        conversation = await self._conversations.get(phone)
        if conversation is None:
            raise ConversationNotFound(phone)
        return conversation

    async def _save(self, conversation: Conversation) -> None:
        await self._conversations.save(conversation)
        await self._events.publish(
            Event(
                "status_changed",
                conversation.phone,
                {
                    "status": conversation.status.value,
                    "attendant": conversation.attendant,
                    "reason": conversation.handoff_reason,
                },
            )
        )

    async def _send(
        self, conversation: Conversation, text: str, author: str, attendant: str | None
    ) -> ChatEntry:
        message_id = await self._sender.send_text(conversation.phone, text)
        entry = ChatEntry(
            phone=conversation.phone,
            direction="out",
            author=author,
            text=text,
            message_id=message_id,
            attendant=attendant,
        )
        await self._log.append(entry)
        await self._events.publish(Event("message_sent", conversation.phone, entry.to_dict()))
        return entry
