import base64
import json

import pytest

from zapagent.webhook import handler as webhook
from zapagent.webhook.payload import extract_messages
from zapagent.webhook.signature import is_valid_signature, sign, verify_challenge

SECRET = "app-secret"


def payload(*messages: dict, contacts: list | None = None) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID"},
                            "contacts": contacts
                            or [{"profile": {"name": "Ana"}, "wa_id": "5511999990001"}],
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


TEXT = {
    "from": "5511999990001",
    "id": "wamid.1",
    "timestamp": "1700000000",
    "type": "text",
    "text": {"body": "Oi, cadê meu pedido?"},
}


def test_signature_roundtrip() -> None:
    body = b'{"a": 1}'
    assert is_valid_signature(body, sign(body, SECRET), SECRET)


@pytest.mark.parametrize(
    "header", [None, "", "sha1=abc", "sha256=deadbeef", sign(b"outro corpo", SECRET)]
)
def test_rejects_invalid_signatures(header: str | None) -> None:
    assert not is_valid_signature(b'{"a": 1}', header, SECRET)


def test_rejects_when_secret_is_not_configured() -> None:
    body = b"{}"
    assert not is_valid_signature(body, sign(body, ""), "")


def test_verify_challenge() -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"}
    assert verify_challenge(params, "tok") == "42"
    assert verify_challenge({**params, "hub.verify_token": "x"}, "tok") is None
    assert verify_challenge({**params, "hub.mode": "unsubscribe"}, "tok") is None


def test_extracts_text_and_media_messages() -> None:
    image = {
        "from": "5511999990001",
        "id": "wamid.2",
        "timestamp": "1700000001",
        "type": "image",
        "image": {"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "produto quebrado"},
    }
    messages = extract_messages(payload(TEXT, image))
    assert messages[0]["text"] == "Oi, cadê meu pedido?"
    assert messages[0]["name"] == "Ana"
    assert messages[0]["phone_number_id"] == "PNID"
    assert messages[1]["media_id"] == "MEDIA1"
    assert messages[1]["text"] == "produto quebrado"


def test_ignores_status_updates_and_other_objects() -> None:
    statuses = payload()
    statuses["entry"][0]["changes"][0]["value"]["statuses"] = [{"id": "wamid.1"}]
    assert extract_messages(statuses) == []
    assert extract_messages({"object": "page", "entry": []}) == []


class FakeSqs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message(self, **kwargs) -> dict:
        self.sent.append(kwargs)
        return {"MessageId": "1"}


@pytest.fixture
def sqs(monkeypatch) -> FakeSqs:
    fake = FakeSqs()
    monkeypatch.setattr(webhook, "_sqs", lambda: fake)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok")
    monkeypatch.setenv("INBOUND_QUEUE_URL", "http://queue")
    return fake


def signed_event(body: bytes, http_api: bool = False, base64_body: bool = False) -> dict:
    event = {
        "headers": {"X-Hub-Signature-256": sign(body, SECRET)},
        "body": base64.b64encode(body).decode() if base64_body else body.decode(),
        "isBase64Encoded": base64_body,
    }
    if http_api:
        event["requestContext"] = {"http": {"method": "POST"}}
    else:
        event["httpMethod"] = "POST"
    return event


@pytest.mark.parametrize("http_api,base64_body", [(False, False), (True, True)])
def test_handler_enqueues_signed_messages(sqs: FakeSqs, http_api: bool, base64_body: bool) -> None:
    body = json.dumps(payload(TEXT), ensure_ascii=False).encode()

    response = webhook.handler(signed_event(body, http_api, base64_body))

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"queued": 1}
    message = json.loads(sqs.sent[0]["MessageBody"])
    assert message["message_id"] == "wamid.1"
    assert sqs.sent[0]["QueueUrl"] == "http://queue"


def test_handler_rejects_bad_signature_without_enqueuing(sqs: FakeSqs) -> None:
    event = signed_event(json.dumps(payload(TEXT)).encode())
    event["headers"]["X-Hub-Signature-256"] = "sha256=forjada"

    assert webhook.handler(event)["statusCode"] == 401
    assert sqs.sent == []


def test_handler_answers_verification_challenge(sqs: FakeSqs) -> None:
    event = {
        "httpMethod": "GET",
        "queryStringParameters": {
            "hub.mode": "subscribe",
            "hub.verify_token": "tok",
            "hub.challenge": "1158201444",
        },
    }
    response = webhook.handler(event)
    assert response["statusCode"] == 200
    assert response["body"] == "1158201444"

    event["queryStringParameters"]["hub.verify_token"] = "errado"
    assert webhook.handler(event)["statusCode"] == 403
