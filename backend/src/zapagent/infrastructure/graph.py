import httpx


class GraphApiError(Exception):
    pass


class WhatsAppGraphClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        version: str,
        token: str,
        phone_number_id: str,
    ) -> None:
        self._client = client
        self._base = f"{base_url.rstrip('/')}/{version}"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._phone_number_id = phone_number_id

    async def send_text(self, phone: str, text: str) -> str:
        response = await self._client.post(
            f"{self._base}/{self._phone_number_id}/messages",
            headers=self._headers,
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            },
        )
        if response.status_code >= 400:
            raise GraphApiError(f"Graph API {response.status_code}: {response.text[:300]}")
        return response.json()["messages"][0]["id"]

    async def download(self, media_id: str) -> tuple[bytes, str]:
        meta = await self._client.get(f"{self._base}/{media_id}", headers=self._headers)
        if meta.status_code >= 400:
            raise GraphApiError(f"Mídia {media_id} indisponível: {meta.status_code}")
        info = meta.json()
        content = await self._client.get(info["url"], headers=self._headers)
        if content.status_code >= 400:
            raise GraphApiError(f"Download da mídia {media_id} falhou: {content.status_code}")
        return content.content, info.get("mime_type", "application/octet-stream")
