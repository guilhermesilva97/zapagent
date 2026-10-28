import hashlib
import hmac

PREFIX = "sha256="


def sign(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{PREFIX}{digest}"


def is_valid_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    if not header or not header.startswith(PREFIX) or not app_secret:
        return False
    return hmac.compare_digest(sign(body, app_secret), header)


def verify_challenge(params: dict[str, str], verify_token: str) -> str | None:
    if params.get("hub.mode") != "subscribe":
        return None
    if not verify_token or not hmac.compare_digest(
        params.get("hub.verify_token", ""), verify_token
    ):
        return None
    return params.get("hub.challenge")
