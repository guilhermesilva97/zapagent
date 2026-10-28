import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from zapagent.application.attendant import ConversationNotFound
from zapagent.domain.conversation import Event, InvalidTransition
from zapagent.entrypoints.container import Container, build_container
from zapagent.infrastructure.mongo import ensure_indexes, serialize
from zapagent.store.seed import CUSTOMERS
from zapagent.webhook.signature import sign

logger = logging.getLogger("zapagent.api")

WEBHOOK_TIMEOUT_SECONDS = 120


class SimulatedMessage(BaseModel):
    phone: str = Field(pattern=r"^\d{10,15}$")
    name: str = Field(default="", max_length=80)
    text: str = Field(min_length=1, max_length=2000)


class AssumeRequest(BaseModel):
    attendant: str = Field(min_length=2, max_length=60)


class ReplyRequest(BaseModel):
    attendant: str = Field(min_length=2, max_length=60)
    text: str = Field(min_length=1, max_length=2000)


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await ensure_indexes(container.database)
        yield
        await container.http.aclose()

    app = FastAPI(title="ZapAgent API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(_panel_router(container))
    app.include_router(_simulator_router(container))
    app.include_router(_graph_router(container))
    return app


def _panel_router(container: Container) -> APIRouter:
    router = APIRouter(prefix="/api")
    desk = container.attendant_desk()

    @router.get("/conversations")
    async def conversations() -> list[dict[str, Any]]:
        return await container.conversations.list_all()

    @router.get("/conversations/{phone}/messages")
    async def messages(phone: str) -> list[dict[str, Any]]:
        return await container.log.history(phone)

    @router.get("/conversations/{phone}/events")
    async def events(phone: str) -> list[dict[str, Any]]:
        return await container.events.for_phone(phone)

    @router.post("/conversations/{phone}/assume")
    async def assume(phone: str, request: AssumeRequest) -> dict[str, Any]:
        return await _desk_action(lambda: desk.assume(phone, request.attendant))

    @router.post("/conversations/{phone}/release")
    async def release(phone: str) -> dict[str, Any]:
        return await _desk_action(lambda: desk.release(phone))

    @router.post("/conversations/{phone}/reply")
    async def reply(phone: str, request: ReplyRequest) -> dict[str, Any]:
        return await _desk_action(lambda: desk.reply(phone, request.attendant, request.text))

    @router.get("/events")
    async def stream() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(container),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def _desk_action(action) -> dict[str, Any]:
    try:
        result = await action()
    except ConversationNotFound as error:
        raise HTTPException(404, f"Conversa {error} não encontrada.") from error
    except InvalidTransition as error:
        raise HTTPException(409, str(error)) from error
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return serialize(
        {
            "phone": result.phone,
            "status": result.status.value,
            "attendant": result.attendant,
            "handoff_reason": result.handoff_reason,
        }
    )


async def _event_stream(container: Container) -> AsyncIterator[str]:
    pipeline = [{"$match": {"operationType": "insert"}}]
    async with await container.database.events.watch(pipeline, max_await_time_ms=10000) as changes:
        yield ": conectado\n\n"
        while changes.alive:
            change = await changes.try_next()
            if change is None:
                yield ": ping\n\n"
                continue
            document = serialize(change["fullDocument"])
            yield f"event: {document['type']}\ndata: {json.dumps(document, ensure_ascii=False)}\n\n"


def _simulator_router(container: Container) -> APIRouter:
    router = APIRouter(prefix="/api/simulator")
    settings = container.settings
    chat = container.database.sim_chat
    media = container.database.sim_media

    @router.get("/contacts")
    async def contacts() -> list[dict[str, str]]:
        return [{"phone": phone, "name": name} for phone, name in CUSTOMERS.items()]

    @router.get("/chats/{phone}")
    async def history(phone: str) -> list[dict[str, Any]]:
        cursor = chat.find({"phone": phone}).sort("at", 1)
        return [serialize(document) async for document in cursor]

    @router.post("/messages")
    async def send_text(message: SimulatedMessage) -> dict[str, Any]:
        content = {"type": "text", "text": {"body": message.text}}
        return await _deliver(message.phone, message.name, content, message.text, False)

    @router.post("/media")
    async def send_media(
        phone: Annotated[str, Form(pattern=r"^\d{10,15}$")],
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form()] = "",
        caption: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        data = await file.read()
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(413, "O simulador aceita arquivos de até 2 MB.")
        mime_type = file.content_type or "application/octet-stream"
        media_id = secrets.token_hex(8)
        await media.insert_one({"_id": media_id, "mime_type": mime_type, "content": data})
        kind = "image" if mime_type.startswith("image/") else "document"
        content = {"type": kind, kind: {"id": media_id, "mime_type": mime_type, "caption": caption}}
        return await _deliver(phone, name, content, caption or f"[{kind}]", True)

    async def _deliver(
        phone: str, name: str, content: dict[str, Any], text: str, has_media: bool
    ) -> dict[str, Any]:
        message_id = f"wamid.SIM{secrets.token_hex(10).upper()}"
        payload = _webhook_payload(settings.phone_number_id, phone, name, message_id, content)
        body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            response = await container.http.post(
                settings.webhook_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sign(body, settings.whatsapp_app_secret),
                },
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logger.exception("Webhook indisponível")
            raise HTTPException(502, f"Webhook indisponível: {error}") from error
        if response.status_code >= 400:
            raise HTTPException(502, f"Webhook respondeu {response.status_code}: {response.text}")
        await chat.insert_one(
            {
                "phone": phone,
                "direction": "from_phone",
                "text": text,
                "media": has_media,
                "message_id": message_id,
                "at": datetime.now(UTC),
            }
        )
        return {"message_id": message_id, "webhook_status": response.status_code}

    return router


def _webhook_payload(
    phone_number_id: str, phone: str, name: str, message_id: str, content: dict[str, Any]
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA-SIMULADOR",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5511900000000",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [{"profile": {"name": name}, "wa_id": phone}],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    **content,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _graph_router(container: Container) -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["graph-api-simulada"])
    settings = container.settings
    database = container.database

    def authorize(authorization: str | None) -> None:
        if authorization != f"Bearer {settings.graph_token}":
            raise HTTPException(401, "Token da Graph API inválido.")

    @router.post("/{version}/{phone_number_id}/messages")
    async def send_message(
        version: str,
        phone_number_id: str,
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        if phone_number_id != settings.phone_number_id:
            raise HTTPException(404, "phone_number_id desconhecido.")
        if payload.get("type") != "text":
            raise HTTPException(400, "O simulador só entrega mensagens de texto.")
        phone = str(payload.get("to", ""))
        text = payload.get("text", {}).get("body", "")
        message_id = f"wamid.OUT{secrets.token_hex(10).upper()}"
        await database.sim_chat.insert_one(
            {
                "phone": phone,
                "direction": "to_phone",
                "text": text,
                "media": False,
                "message_id": message_id,
                "at": datetime.now(UTC),
            }
        )
        await container.events.publish(
            Event("simulator_delivery", phone, {"text": text, "message_id": message_id})
        )
        return {
            "messaging_product": "whatsapp",
            "contacts": [{"input": phone, "wa_id": phone}],
            "messages": [{"id": message_id}],
        }

    @router.get("/media/{media_id}/download")
    async def download_media(
        media_id: str, authorization: str | None = Header(default=None)
    ) -> Response:
        authorize(authorization)
        document = await database.sim_media.find_one({"_id": media_id})
        if document is None:
            raise HTTPException(404, "Mídia não encontrada.")
        return Response(content=bytes(document["content"]), media_type=document["mime_type"])

    @router.get("/{version}/{media_id}")
    async def media_info(
        version: str,
        media_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(authorization)
        document = await database.sim_media.find_one({"_id": media_id}, {"content": 0})
        if document is None:
            raise HTTPException(404, "Mídia não encontrada.")
        url = str(request.url_for("download_media", media_id=media_id))
        return {"id": media_id, "url": url, "mime_type": document["mime_type"]}

    return router
