from datetime import UTC, datetime
from typing import Any

import pytest

from zapagent.store.seed import build_orders
from zapagent.store.service import StoreError, StoreService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
ANA = "5511999990001"
BRUNO = "5511999990002"


class MemoryStore:
    def __init__(self) -> None:
        self.orders = {order["_id"]: order for order in build_orders(NOW)}
        self.exchanges: list[dict[str, Any]] = []
        self.tickets: list[dict[str, Any]] = []

    async def find_order(self, number: str) -> dict[str, Any] | None:
        return self.orders.get(number)

    async def find_open_exchange(self, number: str) -> dict[str, Any] | None:
        return next((e for e in self.exchanges if e["pedido"] == number), None)

    async def insert_exchange(self, document: dict[str, Any]) -> None:
        self.exchanges.append(document)

    async def insert_ticket(self, document: dict[str, Any]) -> None:
        self.tickets.append(document)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def service(store: MemoryStore) -> StoreService:
    return StoreService(store, clock=lambda: NOW, protocol=lambda prefix, _: f"{prefix}-TESTE")


async def test_order_is_only_visible_to_its_owner(service: StoreService) -> None:
    summary = await service.order_summary(ANA, "#1001")
    assert summary["status"] == "em_transporte"

    with pytest.raises(StoreError, match="vinculado a este número"):
        await service.order_summary(BRUNO, "1001")


async def test_tracking_explains_orders_without_shipment(service: StoreService) -> None:
    tracking = await service.tracking(ANA, "1001")
    assert tracking["codigo_rastreio"] == "RL123456789BR"
    assert len(tracking["eventos"]) == 3

    pending = await service.tracking(BRUNO, "1004")
    assert "pagamento" in pending["mensagem"]


async def test_schedules_exchange_within_the_window(
    service: StoreService, store: MemoryStore
) -> None:
    result = await service.schedule_exchange(ANA, "1002", "tamanho errado", "2026-03-12")

    assert result == {"protocolo": "TR-TESTE", "pedido": "1002", "data_coleta": "2026-03-12"}
    assert store.exchanges[0]["motivo"] == "tamanho errado"

    with pytest.raises(StoreError, match="Já existe"):
        await service.schedule_exchange(ANA, "1002", "outro", "2026-03-13")


@pytest.mark.parametrize(
    "phone,order,date,message",
    [
        (BRUNO, "1003", "2026-03-12", "prazo de troca"),
        (ANA, "1001", "2026-03-12", "já entregues"),
        (ANA, "1002", "2026-03-10", "a partir de amanhã"),
        (ANA, "1002", "2026-03-15", "domingos"),
        (ANA, "1002", "12/03/2026", "formato"),
    ],
)
async def test_rejects_invalid_exchanges(
    service: StoreService, phone: str, order: str, date: str, message: str
) -> None:
    with pytest.raises(StoreError, match=message):
        await service.schedule_exchange(phone, order, "defeito", date)


async def test_tickets_and_handoff_get_protocols(service: StoreService, store: MemoryStore) -> None:
    ticket = await service.open_ticket(ANA, "Cobrança", "Fui cobrada duas vezes")
    handoff = await service.request_human(ANA, "cliente irritado")

    assert ticket["protocolo"] == "CH-TESTE"
    assert handoff == {"protocolo": "AT-TESTE", "status": "aberto", "handoff": True}
    assert [t["tipo"] for t in store.tickets] == ["chamado", "atendimento_humano"]
