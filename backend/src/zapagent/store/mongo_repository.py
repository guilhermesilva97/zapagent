from typing import Any

from pymongo.asynchronous.database import AsyncDatabase


class MongoStoreRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._db = database

    async def find_order(self, number: str) -> dict[str, Any] | None:
        return await self._db.orders.find_one({"_id": number})

    async def find_open_exchange(self, number: str) -> dict[str, Any] | None:
        return await self._db.exchanges.find_one({"pedido": number, "status": "agendada"})

    async def insert_exchange(self, document: dict[str, Any]) -> None:
        await self._db.exchanges.insert_one(document)

    async def insert_ticket(self, document: dict[str, Any]) -> None:
        await self._db.tickets.insert_one(document)
