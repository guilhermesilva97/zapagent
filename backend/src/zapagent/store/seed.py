from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ReplaceOne
from pymongo.asynchronous.database import AsyncDatabase

CUSTOMERS = {
    "5511999990001": "Ana Souza",
    "5511999990002": "Bruno Lima",
    "5511999990003": "Carla Mendes",
}


def _event(moment: datetime, description: str, place: str) -> dict[str, Any]:
    return {"em": moment, "descricao": description, "local": place}


def build_orders(now: datetime) -> list[dict[str, Any]]:
    day = timedelta(days=1)
    return [
        {
            "_id": "1001",
            "telefone": "5511999990001",
            "cliente": CUSTOMERS["5511999990001"],
            "status": "em_transporte",
            "criado_em": now - 4 * day,
            "entregue_em": None,
            "total": 459.80,
            "itens": [
                {"produto": "Tênis de Corrida Aurora Run", "quantidade": 1, "preco": 399.90},
                {"produto": "Meia Esportiva (par)", "quantidade": 2, "preco": 29.95},
            ],
            "entrega": {
                "transportadora": "Rápido Log",
                "codigo_rastreio": "RL123456789BR",
                "previsao": (now + 2 * day).date().isoformat(),
                "eventos": [
                    _event(now - 3 * day, "Pedido coletado pela transportadora", "São Paulo/SP"),
                    _event(
                        now - 2 * day, "Em trânsito para o centro de distribuição", "Campinas/SP"
                    ),
                    _event(now - 1 * day, "Chegou ao centro de distribuição", "Ribeirão Preto/SP"),
                ],
            },
        },
        {
            "_id": "1002",
            "telefone": "5511999990001",
            "cliente": CUSTOMERS["5511999990001"],
            "status": "entregue",
            "criado_em": now - 12 * day,
            "entregue_em": now - 5 * day,
            "total": 189.90,
            "itens": [{"produto": "Jaqueta Corta-Vento", "quantidade": 1, "preco": 189.90}],
            "entrega": {
                "transportadora": "Rápido Log",
                "codigo_rastreio": "RL987654321BR",
                "previsao": (now - 5 * day).date().isoformat(),
                "eventos": [
                    _event(now - 8 * day, "Pedido coletado pela transportadora", "São Paulo/SP"),
                    _event(now - 5 * day, "Entregue ao destinatário", "Ribeirão Preto/SP"),
                ],
            },
        },
        {
            "_id": "1003",
            "telefone": "5511999990002",
            "cliente": CUSTOMERS["5511999990002"],
            "status": "entregue",
            "criado_em": now - 60 * day,
            "entregue_em": now - 45 * day,
            "total": 249.00,
            "itens": [{"produto": "Mochila Executiva", "quantidade": 1, "preco": 249.00}],
            "entrega": {
                "transportadora": "Correios",
                "codigo_rastreio": "QB112233445BR",
                "previsao": (now - 45 * day).date().isoformat(),
                "eventos": [_event(now - 45 * day, "Entregue ao destinatário", "Curitiba/PR")],
            },
        },
        {
            "_id": "1004",
            "telefone": "5511999990002",
            "cliente": CUSTOMERS["5511999990002"],
            "status": "aguardando_pagamento",
            "criado_em": now - 1 * day,
            "entregue_em": None,
            "total": 89.90,
            "itens": [{"produto": "Garrafa Térmica 1L", "quantidade": 1, "preco": 89.90}],
            "entrega": {},
        },
        {
            "_id": "1005",
            "telefone": "5511999990003",
            "cliente": CUSTOMERS["5511999990003"],
            "status": "cancelado",
            "criado_em": now - 20 * day,
            "entregue_em": None,
            "total": 599.00,
            "itens": [{"produto": "Relógio Smart Aurora", "quantidade": 1, "preco": 599.00}],
            "entrega": {},
        },
    ]


async def seed_store(database: AsyncDatabase, now: datetime | None = None) -> int:
    orders = build_orders(now or datetime.now(UTC))
    result = await database.orders.bulk_write(
        [ReplaceOne({"_id": order["_id"]}, order, upsert=True) for order in orders]
    )
    await database.exchanges.delete_many({})
    return result.upserted_count + result.modified_count
