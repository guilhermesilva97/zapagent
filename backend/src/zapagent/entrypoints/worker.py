import asyncio
import logging
import signal
from typing import Any

import boto3

from zapagent.application.process_inbound import ProcessInboundMessage
from zapagent.domain.conversation import InboundMessage
from zapagent.entrypoints.container import build_container
from zapagent.infrastructure.aws import S3MediaStorage, SqsConsumer
from zapagent.infrastructure.mongo import ensure_indexes

logger = logging.getLogger("zapagent.worker")


async def main() -> None:
    container = build_container()
    settings = container.settings
    await ensure_indexes(container.database)

    sqs = boto3.client("sqs", region_name=settings.aws_region)
    s3 = boto3.client("s3", region_name=settings.aws_region)
    queue_url = sqs.get_queue_url(QueueName=settings.inbound_queue_name)["QueueUrl"]

    use_case = ProcessInboundMessage(
        conversations=container.conversations,
        log=container.log,
        idempotency=container.idempotency,
        events=container.events,
        sender=container.graph,
        downloader=container.graph,
        storage=S3MediaStorage(s3, settings.media_bucket),
        agent=container.agent(),
        history_limit=settings.history_limit,
    )

    async def handle(body: dict[str, Any]) -> None:
        result = await use_case.execute(InboundMessage.from_dict(body))
        logger.info("Mensagem %s de %s: %s", body.get("message_id"), body.get("phone"), result)

    consumer = SqsConsumer(sqs, queue_url, handle)
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(stop_signal, consumer.stop)
    await consumer.run()
    await container.http.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
