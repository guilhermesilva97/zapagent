import base64
import json
import logging
import os
from functools import cache
from typing import Any

from zapagent.webhook.payload import extract_messages
from zapagent.webhook.signature import is_valid_signature, verify_challenge

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@cache
def _sqs():
    import boto3

    return boto3.client("sqs")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    if _method(event) == "GET":
        challenge = verify_challenge(
            event.get("queryStringParameters") or {}, os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        )
        if challenge is None:
            return _response(403, "forbidden")
        return _response(200, challenge, content_type="text/plain")

    body = _raw_body(event)
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not is_valid_signature(body, headers.get("x-hub-signature-256"), secret):
        logger.warning("Assinatura inválida rejeitada")
        return _response(401, "invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _response(400, "invalid json")

    messages = extract_messages(payload)
    queue_url = os.environ["INBOUND_QUEUE_URL"]
    for message in messages:
        _sqs().send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message, ensure_ascii=False),
            MessageAttributes={
                "message_id": {"DataType": "String", "StringValue": message["message_id"] or "-"}
            },
        )
    logger.info("Webhook aceito com %s mensagem(ns)", len(messages))
    return _response(200, json.dumps({"queued": len(messages)}), content_type="application/json")


def _method(event: dict[str, Any]) -> str:
    return (
        event.get("httpMethod")
        or event.get("requestContext", {}).get("http", {}).get("method")
        or "POST"
    ).upper()


def _raw_body(event: dict[str, Any]) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode()


def _response(status: int, body: str, content_type: str = "text/plain") -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": content_type}, "body": body}
