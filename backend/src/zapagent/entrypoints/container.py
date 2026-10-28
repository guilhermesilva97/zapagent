from dataclasses import dataclass
from functools import partial

import httpx
from openai import AsyncOpenAI
from pymongo.asynchronous.database import AsyncDatabase

from zapagent.application.agent import RunAgent
from zapagent.application.attendant import AttendantDesk
from zapagent.application.ports import EventPublisher
from zapagent.config import Settings
from zapagent.infrastructure.graph import WhatsAppGraphClient
from zapagent.infrastructure.mcp_gateway import open_mcp_gateway
from zapagent.infrastructure.mongo import (
    MongoConversationRepository,
    MongoEventPublisher,
    MongoIdempotencyStore,
    MongoMessageLog,
    connect,
)
from zapagent.infrastructure.openai_model import OpenAICompatibleModel


@dataclass
class Container:
    settings: Settings
    database: AsyncDatabase
    http: httpx.AsyncClient
    conversations: MongoConversationRepository
    log: MongoMessageLog
    idempotency: MongoIdempotencyStore
    events: MongoEventPublisher
    graph: WhatsAppGraphClient

    def agent(self, events: EventPublisher | None = None) -> RunAgent:
        client = AsyncOpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=1,
        )
        return RunAgent(
            model=OpenAICompatibleModel(
                client,
                self.settings.llm_model,
                temperature=self.settings.llm_temperature,
                reasoning_effort=self.settings.llm_reasoning_effort,
            ),
            gateway_factory=partial(open_mcp_gateway, self.settings.mcp_server_url),
            events=events or self.events,
            store_name=self.settings.store_name,
            max_steps=self.settings.agent_max_steps,
        )

    def attendant_desk(self) -> AttendantDesk:
        return AttendantDesk(self.conversations, self.log, self.events, self.graph)


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    database = connect(settings.mongo_url, settings.mongo_db)
    http = httpx.AsyncClient(timeout=30)
    return Container(
        settings=settings,
        database=database,
        http=http,
        conversations=MongoConversationRepository(database),
        log=MongoMessageLog(database),
        idempotency=MongoIdempotencyStore(database),
        events=MongoEventPublisher(database),
        graph=WhatsAppGraphClient(
            http,
            settings.graph_base_url,
            settings.graph_api_version,
            settings.graph_token,
            settings.phone_number_id,
        ),
    )
