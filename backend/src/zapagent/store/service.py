import secrets
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

EXCHANGE_WINDOW_DAYS = 30
NO_TRACKING_STATUSES = {
    "aguardando_pagamento": "O pagamento ainda não foi confirmado, por isso não há rastreio.",
    "em_separacao": "O pedido está em separação e ainda não foi entregue à transportadora.",
    "cancelado": "O pedido foi cancelado e não possui entrega.",
}


class StoreError(Exception):
    pass


class StoreRepository(Protocol):
    async def find_order(self, number: str) -> dict[str, Any] | None: ...

    async def find_open_exchange(self, number: str) -> dict[str, Any] | None: ...

    async def insert_exchange(self, document: dict[str, Any]) -> None: ...

    async def insert_ticket(self, document: dict[str, Any]) -> None: ...


def _protocol(prefix: str, moment: datetime) -> str:
    return f"{prefix}-{moment:%Y%m%d}-{secrets.token_hex(2).upper()}"


class StoreService:
    def __init__(
        self,
        repository: StoreRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        protocol: Callable[[str, datetime], str] = _protocol,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._protocol = protocol

    async def order_summary(self, phone: str, number: str) -> dict[str, Any]:
        order = await self._owned_order(phone, number)
        return {
            "numero_pedido": order["_id"],
            "status": order["status"],
            "criado_em": _iso(order.get("criado_em")),
            "entregue_em": _iso(order.get("entregue_em")),
            "total": order.get("total"),
            "itens": order.get("itens", []),
            "previsao_entrega": _iso(order.get("entrega", {}).get("previsao")),
        }

    async def tracking(self, phone: str, number: str) -> dict[str, Any]:
        order = await self._owned_order(phone, number)
        if order["status"] in NO_TRACKING_STATUSES:
            return {
                "numero_pedido": order["_id"],
                "status": order["status"],
                "mensagem": NO_TRACKING_STATUSES[order["status"]],
            }
        delivery = order.get("entrega", {})
        return {
            "numero_pedido": order["_id"],
            "status": order["status"],
            "transportadora": delivery.get("transportadora"),
            "codigo_rastreio": delivery.get("codigo_rastreio"),
            "previsao_entrega": _iso(delivery.get("previsao")),
            "eventos": [
                {"em": _iso(event["em"]), "descricao": event["descricao"], "local": event["local"]}
                for event in delivery.get("eventos", [])
            ],
        }

    async def schedule_exchange(
        self, phone: str, number: str, reason: str, pickup_date: str
    ) -> dict[str, Any]:
        order = await self._owned_order(phone, number)
        now = self._clock()
        if order["status"] != "entregue":
            raise StoreError("Só é possível trocar pedidos já entregues.")
        delivered_at = _as_utc(order["entregue_em"])
        if now - delivered_at > timedelta(days=EXCHANGE_WINDOW_DAYS):
            raise StoreError(
                f"O prazo de troca é de {EXCHANGE_WINDOW_DAYS} dias após a entrega "
                f"e este pedido foi entregue em {delivered_at:%d/%m/%Y}."
            )
        if not reason.strip():
            raise StoreError("Informe o motivo da troca.")
        pickup = _parse_date(pickup_date)
        today = now.date()
        if pickup <= today or pickup > today + timedelta(days=EXCHANGE_WINDOW_DAYS):
            raise StoreError("A data de coleta deve ser a partir de amanhã e em até 30 dias.")
        if pickup.weekday() == 6:
            raise StoreError("Não fazemos coletas aos domingos.")
        if await self._repository.find_open_exchange(order["_id"]):
            raise StoreError("Já existe uma troca agendada para este pedido.")

        protocol = self._protocol("TR", now)
        await self._repository.insert_exchange(
            {
                "_id": protocol,
                "pedido": order["_id"],
                "telefone": phone,
                "motivo": reason,
                "data_coleta": pickup.isoformat(),
                "status": "agendada",
                "criado_em": now,
            }
        )
        return {"protocolo": protocol, "pedido": order["_id"], "data_coleta": pickup.isoformat()}

    async def open_ticket(self, phone: str, subject: str, description: str) -> dict[str, Any]:
        if not subject.strip() or not description.strip():
            raise StoreError("Informe assunto e descrição do chamado.")
        return await self._ticket("CH", "chamado", phone, subject, description)

    async def request_human(self, phone: str, reason: str) -> dict[str, Any]:
        result = await self._ticket(
            "AT", "atendimento_humano", phone, "Transferência para atendente", reason or "-"
        )
        return {**result, "handoff": True}

    async def _ticket(
        self, prefix: str, kind: str, phone: str, subject: str, description: str
    ) -> dict[str, Any]:
        now = self._clock()
        protocol = self._protocol(prefix, now)
        await self._repository.insert_ticket(
            {
                "_id": protocol,
                "tipo": kind,
                "telefone": phone,
                "assunto": subject,
                "descricao": description,
                "status": "aberto",
                "criado_em": now,
            }
        )
        return {"protocolo": protocol, "status": "aberto"}

    async def _owned_order(self, phone: str, number: str) -> dict[str, Any]:
        normalized = "".join(ch for ch in str(number) if ch.isdigit())
        order = await self._repository.find_order(normalized) if normalized else None
        if order is None or order.get("telefone") != phone:
            raise StoreError(f"Não encontrei o pedido {number} vinculado a este número.")
        return order


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError) as error:
        raise StoreError("Data inválida; use o formato AAAA-MM-DD.") from error


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
