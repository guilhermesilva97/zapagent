import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("zapagent.sqs")


class S3MediaStorage:
    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    async def store(self, key: str, content: bytes, mime_type: str) -> str:
        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=mime_type,
        )
        return f"s3://{self._bucket}/{key}"


class SqsConsumer:
    def __init__(
        self,
        sqs_client: Any,
        queue_url: str,
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
        wait_seconds: int = 10,
        retry_delay_seconds: int = 5,
    ) -> None:
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._handler = handler
        self._wait_seconds = wait_seconds
        self._retry_delay = retry_delay_seconds
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        logger.info("Consumindo %s", self._queue_url)
        while self._running:
            await self.poll_once()

    async def poll_once(self) -> int:
        response = await asyncio.to_thread(
            self._sqs.receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=self._wait_seconds,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            await self._process(message)
        return len(messages)

    async def _process(self, message: dict[str, Any]) -> None:
        receipt = message["ReceiptHandle"]
        attempt = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            await self._handler(json.loads(message["Body"]))
        except Exception:
            logger.exception("Falha na tentativa %s; a mensagem volta para a fila", attempt)
            await asyncio.to_thread(
                self._sqs.change_message_visibility,
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=self._retry_delay * attempt,
            )
            return
        await asyncio.to_thread(
            self._sqs.delete_message, QueueUrl=self._queue_url, ReceiptHandle=receipt
        )
