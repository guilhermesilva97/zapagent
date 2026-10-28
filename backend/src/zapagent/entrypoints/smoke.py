import base64
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
PHONE = "5511999990003"
NAME = "Carla Mendes"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class SmokeFailure(Exception):
    pass


def wait_for(description: str, check: Callable[[], Any], timeout: float = 180) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            print(f"  ok: {description}")
            return result
        time.sleep(2)
    raise SmokeFailure(f"tempo esgotado esperando: {description}")


def run(client: httpx.Client) -> None:
    def phone_chat() -> list[dict[str, Any]]:
        return client.get(f"/api/simulator/chats/{PHONE}").raise_for_status().json()

    def conversation() -> dict[str, Any] | None:
        items = client.get("/api/conversations").raise_for_status().json()
        return next((item for item in items if item["id"] == PHONE), None)

    def delivered_after(count: int) -> Callable[[], list[dict[str, Any]]]:
        return lambda: [m for m in phone_chat() if m["direction"] == "to_phone"][count:]

    existing = conversation()
    if existing and existing["status"] != "bot":
        client.post(f"/api/conversations/{PHONE}/release").raise_for_status()
        print("0. Conversa de uma execução anterior devolvida ao assistente")

    already = len([m for m in phone_chat() if m["direction"] == "to_phone"])

    print("1. Cliente envia mensagem assinada pelo simulador (API Gateway -> Lambda -> SQS)")
    response = client.post(
        "/api/simulator/messages",
        json={"phone": PHONE, "name": NAME, "text": "Qual o status do pedido 1005?"},
    )
    response.raise_for_status()
    if response.json()["webhook_status"] != 200:
        raise SmokeFailure(f"webhook respondeu {response.json()}")
    print(f"  ok: webhook aceitou {response.json()['message_id']}")

    print("2. Worker consome a fila e responde pelo WhatsApp")
    replies = wait_for("resposta entregue ao celular", delivered_after(already))
    print(f"     resposta: {replies[-1]['text']!r}")
    state = wait_for("conversa registrada", conversation)
    print(f"     status da conversa: {state['status']} ({state.get('handoff_reason')})")

    print("3. Atendente assume, responde e devolve a conversa")
    delivered = len([m for m in phone_chat() if m["direction"] == "to_phone"])
    client.post(
        f"/api/conversations/{PHONE}/assume", json={"attendant": "Smoke"}
    ).raise_for_status()
    client.post(
        f"/api/conversations/{PHONE}/reply",
        json={"attendant": "Smoke", "text": "Oi Carla, aqui é do time de atendimento."},
    ).raise_for_status()
    wait_for("resposta do atendente no celular", delivered_after(delivered))

    silent_before = len([m for m in phone_chat() if m["direction"] == "to_phone"])
    client.post(
        "/api/simulator/messages",
        json={"phone": PHONE, "name": NAME, "text": "Obrigada!"},
    ).raise_for_status()
    wait_for(
        "mensagem registrada sem resposta do bot",
        lambda: any(
            m["text"] == "Obrigada!"
            for m in client.get(f"/api/conversations/{PHONE}/messages").json()
        ),
    )
    time.sleep(3)
    if len([m for m in phone_chat() if m["direction"] == "to_phone"]) != silent_before:
        raise SmokeFailure("o bot respondeu enquanto a conversa estava com o atendente")
    print("  ok: bot ficou em silêncio durante o atendimento humano")

    client.post(f"/api/conversations/{PHONE}/release").raise_for_status()
    wait_for("conversa devolvida ao assistente", lambda: conversation()["status"] == "bot")

    print("4. Cliente envia imagem; mídia vai para o S3")
    client.post(
        "/api/simulator/media",
        data={"phone": PHONE, "name": NAME, "caption": "foto da etiqueta"},
        files={"file": ("etiqueta.png", TINY_PNG, "image/png")},
    ).raise_for_status()
    wait_for(
        "mídia salva no S3",
        lambda: any(
            (m.get("media_key") or "").startswith("s3://")
            for m in client.get(f"/api/conversations/{PHONE}/messages").json()
        ),
    )


def main() -> int:
    with httpx.Client(base_url=BASE_URL, timeout=150) as client:
        try:
            run(client)
        except (SmokeFailure, httpx.HTTPError) as error:
            print(f"FALHOU: {error}")
            return 1
    print("Smoke test concluído com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
