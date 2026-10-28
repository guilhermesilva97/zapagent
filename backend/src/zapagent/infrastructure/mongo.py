from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from zapagent.domain.conversation import ChatEntry, Conversation, ConversationStatus, Event


def connect(url: str, database: str) -> AsyncDatabase:
    return AsyncMongoClient(url, tz_aware=True)[database]


async def ensure_indexes(database: AsyncDatabase) -> None:
    await database.messages.create_index([("phone", ASCENDING), ("at", ASCENDING)])
    await database.messages.create_index(
        "message_id",
        unique=True,
        partialFilterExpression={"message_id": {"$type": "string"}},
    )
    await database.events.create_index([("phone", ASCENDING), ("at", ASCENDING)])
    await database.conversations.create_index([("updated_at", DESCENDING)])
    await database.processed_messages.create_index("claimed_at", expireAfterSeconds=7 * 86400)


class MongoConversationRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.conversations

    async def get(self, phone: str) -> Conversation | None:
        document = await self._collection.find_one({"_id": phone})
        return _to_conversation(document) if document else None

    async def get_or_create(self, phone: str, name: str) -> Conversation:
        document = await self._collection.find_one_and_update(
            {"_id": phone},
            {
                "$setOnInsert": {
                    "status": ConversationStatus.BOT.value,
                    "handoff_reason": None,
                    "attendant": None,
                },
                "$set": {"name": name, "updated_at": datetime.now(UTC)},
            },
            upsert=True,
            return_document=True,
        )
        return _to_conversation(document)

    async def save(self, conversation: Conversation) -> None:
        await self._collection.update_one(
            {"_id": conversation.phone},
            {
                "$set": {
                    "name": conversation.name,
                    "status": conversation.status.value,
                    "handoff_reason": conversation.handoff_reason,
                    "attendant": conversation.attendant,
                    "updated_at": conversation.updated_at,
                }
            },
            upsert=True,
        )

    async def list_all(self) -> list[dict[str, Any]]:
        cursor = self._collection.find().sort("updated_at", DESCENDING)
        return [serialize(document) async for document in cursor]


class MongoMessageLog:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.messages

    async def append(self, entry: ChatEntry) -> None:
        document = asdict(entry)
        if not entry.message_id:
            await self._collection.insert_one(document)
            return
        await self._collection.update_one(
            {"message_id": entry.message_id}, {"$setOnInsert": document}, upsert=True
        )

    async def recent(self, phone: str, limit: int) -> list[ChatEntry]:
        cursor = self._collection.find({"phone": phone}).sort("at", DESCENDING).limit(limit)
        documents = [document async for document in cursor]
        return [_to_entry(document) for document in reversed(documents)]

    async def history(self, phone: str) -> list[dict[str, Any]]:
        cursor = self._collection.find({"phone": phone}).sort("at", ASCENDING)
        return [serialize(document) async for document in cursor]


class MongoIdempotencyStore:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.processed_messages

    async def claim(self, message_id: str) -> bool:
        try:
            await self._collection.insert_one({"_id": message_id, "claimed_at": datetime.now(UTC)})
        except DuplicateKeyError:
            return False
        return True

    async def release(self, message_id: str) -> None:
        await self._collection.delete_one({"_id": message_id})


class MongoEventPublisher:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.events

    async def publish(self, event: Event) -> None:
        await self._collection.insert_one(asdict(event))

    async def for_phone(self, phone: str, limit: int = 200) -> list[dict[str, Any]]:
        cursor = self._collection.find({"phone": phone}).sort("at", DESCENDING).limit(limit)
        documents = [serialize(document) async for document in cursor]
        return list(reversed(documents))


def _to_conversation(document: dict[str, Any]) -> Conversation:
    return Conversation(
        phone=document["_id"],
        name=document.get("name", ""),
        status=ConversationStatus(document.get("status", ConversationStatus.BOT.value)),
        handoff_reason=document.get("handoff_reason"),
        attendant=document.get("attendant"),
        updated_at=document.get("updated_at") or datetime.now(UTC),
    )


def _to_entry(document: dict[str, Any]) -> ChatEntry:
    return ChatEntry(
        phone=document["phone"],
        direction=document["direction"],
        author=document["author"],
        text=document.get("text", ""),
        at=document["at"],
        message_id=document.get("message_id"),
        media_key=document.get("media_key"),
        attendant=document.get("attendant"),
    )


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {("id" if key == "_id" else key): serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    return value
