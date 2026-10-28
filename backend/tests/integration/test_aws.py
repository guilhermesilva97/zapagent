import json
import secrets
import time

import boto3
import httpx
import pytest

from tests.integration.conftest import requires_infra
from zapagent.config import Settings
from zapagent.webhook.signature import sign

pytestmark = [pytest.mark.integration, requires_infra]


@pytest.fixture(scope="module")
def sqs():
    return boto3.client("sqs", region_name=Settings().aws_region)


@pytest.fixture(scope="module")
def queue_url(sqs) -> str:
    return sqs.get_queue_url(QueueName=Settings().inbound_queue_name)["QueueUrl"]


def drain(sqs, url: str, wanted_id: str, attempts: int = 15) -> dict | None:
    for _ in range(attempts):
        response = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=2)
        for message in response.get("Messages", []):
            body = json.loads(message["Body"])
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
            if body.get("message_id") == wanted_id:
                return body
    return None


def whatsapp_payload(message_id: str) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID"},
                            "contacts": [{"profile": {"name": "Ana"}, "wa_id": "5511999990001"}],
                            "messages": [
                                {
                                    "from": "5511999990001",
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "Olá, integração!"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def test_signed_webhook_goes_through_api_gateway_and_lambda_to_sqs(sqs, queue_url) -> None:
    settings = Settings()
    message_id = f"wamid.IT{secrets.token_hex(6)}"
    body = whatsapp_payload(message_id)

    response = httpx.post(
        settings.webhook_url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body, settings.whatsapp_app_secret),
        },
        timeout=90,
    )

    assert response.status_code == 200, response.text
    queued = drain(sqs, queue_url, message_id)
    assert queued is not None
    assert queued["text"] == "Olá, integração!"


def test_lambda_rejects_forged_signature(sqs, queue_url) -> None:
    settings = Settings()
    body = whatsapp_payload("wamid.FORJADO")

    response = httpx.post(
        settings.webhook_url,
        content=body,
        headers={"X-Hub-Signature-256": sign(body, "segredo-errado")},
        timeout=90,
    )

    assert response.status_code == 401


def test_lambda_answers_meta_verification() -> None:
    settings = Settings()
    response = httpx.get(
        settings.webhook_url,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "987654",
        },
        timeout=90,
    )
    assert response.status_code == 200
    assert response.text == "987654"


def test_poison_message_ends_up_in_the_dead_letter_queue(sqs, queue_url) -> None:
    settings = Settings()
    dlq_url = sqs.get_queue_url(QueueName=settings.inbound_dlq_name)["QueueUrl"]
    marker = f"poison-{secrets.token_hex(4)}"
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"message_id": marker}))

    moved = None
    for _ in range(20):
        sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, VisibilityTimeout=1, WaitTimeSeconds=0
        )
        time.sleep(1.5)
        moved = drain(sqs, dlq_url, marker, attempts=1)
        if moved:
            break

    assert moved is not None
