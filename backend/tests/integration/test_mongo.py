import json
from datetime import UTC, datetime

import pytest

from tests.integration.conftest import requires_infra
from zapagent.config import Settings
from zapagent.domain.conversation import ChatEntry, ConversationStatus
from zapagent.infrastructure.mongo import (
    MongoConversationRepository,
    MongoIdempotencyStore,
    MongoMessageLog,
    connect,
    ensure_indexes,
)
from zapagent.store.mongo_repository import MongoStoreRepository
from zapagent.store.seed import seed_store
from zapagent.store.server import build_store_server
from zapagent.store.service import StoreService

pytestmark = [pytest.mark.integration, pytest.mark.anyio, requires_infra]

PHONE = "5511999990001"


@pytest.fixture
async def database(settings: Settings):
    database = connect(settings.mongo_url, settings.mongo_db)
    await database.client.drop_database(settings.mongo_db)
    await ensure_indexes(database)
    await seed_store(database)
    yield database
    await database.client.drop_database(settings.mongo_db)
    await database.client.close()


async def test_idempotency_claim_is_atomic(database) -> None:
    store = MongoIdempotencyStore(database)

    assert await store.claim("wamid.X") is True
    assert await store.claim("wamid.X") is False
    await store.release("wamid.X")
    assert await store.claim("wamid.X") is True


async def test_conversation_roundtrip(database) -> None:
    repository = MongoConversationRepository(database)

    conversation = await repository.get_or_create(PHONE, "Ana")
    conversation.request_human("teste")
    await repository.save(conversation)

    loaded = await repository.get(PHONE)
    assert loaded.status == ConversationStatus.WAITING_HUMAN
    assert loaded.updated_at.tzinfo is not None
    assert (await repository.list_all())[0]["id"] == PHONE


async def test_message_log_ignores_redelivered_messages(database) -> None:
    log = MongoMessageLog(database)
    entry = ChatEntry(phone=PHONE, direction="in", author="customer", text="oi", message_id="w1")

    await log.append(entry)
    await log.append(entry)
    await log.append(ChatEntry(phone=PHONE, direction="out", author="bot", text="olá"))

    recent = await log.recent(PHONE, 10)
    assert [e.text for e in recent] == ["oi", "olá"]


async def test_mcp_tools_against_seeded_store(database, settings: Settings) -> None:
    service = StoreService(MongoStoreRepository(database))
    server = build_store_server(service, "127.0.0.1", 0)

    result = await server.call_tool(
        "consultar_pedido", {"telefone": PHONE, "numero_pedido": "1001"}
    )
    blocks = result[0] if isinstance(result, tuple) else result
    assert json.loads(blocks[0].text)["status"] == "em_transporte"

    tomorrow = datetime.now(UTC).date().toordinal() + 1
    pickup = datetime.fromordinal(tomorrow).date()
    if pickup.weekday() == 6:
        pickup = datetime.fromordinal(tomorrow + 1).date()
    result = await server.call_tool(
        "agendar_troca",
        {
            "telefone": PHONE,
            "numero_pedido": "1002",
            "motivo": "tamanho",
            "data_coleta": pickup.isoformat(),
        },
    )
    blocks = result[0] if isinstance(result, tuple) else result
    assert json.loads(blocks[0].text)["protocolo"].startswith("TR-")
    assert await database.exchanges.count_documents({"pedido": "1002"}) == 1
