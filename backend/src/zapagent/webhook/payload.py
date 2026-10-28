from typing import Any

MEDIA_TYPES = ("image", "audio", "document", "video", "sticker")


def extract_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "whatsapp_business_account":
        return []
    messages = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            names = {
                contact.get("wa_id"): contact.get("profile", {}).get("name", "")
                for contact in value.get("contacts", [])
            }
            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
            for message in value.get("messages", []):
                messages.append(_normalize(message, names, phone_number_id))
    return messages


def _normalize(
    message: dict[str, Any], names: dict[str, str], phone_number_id: str
) -> dict[str, Any]:
    kind = message.get("type", "unknown")
    phone = message.get("from", "")
    normalized = {
        "message_id": message.get("id", ""),
        "phone": phone,
        "name": names.get(phone, ""),
        "type": kind,
        "text": "",
        "timestamp": int(message.get("timestamp") or 0),
        "phone_number_id": phone_number_id,
        "media_id": None,
        "mime_type": None,
    }
    if kind == "text":
        normalized["text"] = message.get("text", {}).get("body", "")
    elif kind == "button":
        normalized["text"] = message.get("button", {}).get("text", "")
    elif kind == "interactive":
        reply = message.get("interactive", {})
        chosen = reply.get("button_reply") or reply.get("list_reply") or {}
        normalized["text"] = chosen.get("title", "")
    elif kind in MEDIA_TYPES:
        media = message.get(kind, {})
        normalized["media_id"] = media.get("id")
        normalized["mime_type"] = media.get("mime_type")
        normalized["text"] = media.get("caption", "")
    return normalized
