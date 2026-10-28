from zapagent.config import Settings
from zapagent.infrastructure.mongo import connect
from zapagent.store.mongo_repository import MongoStoreRepository
from zapagent.store.server import build_store_server
from zapagent.store.service import StoreService


def main() -> None:
    settings = Settings()
    service = StoreService(MongoStoreRepository(connect(settings.mongo_url, settings.mongo_db)))
    build_store_server(service, settings.mcp_host, settings.mcp_port).run(
        transport="streamable-http"
    )


if __name__ == "__main__":
    main()
