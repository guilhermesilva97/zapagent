import asyncio
import base64
import contextlib
import hashlib
import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

import zapagent
from zapagent.config import Settings
from zapagent.infrastructure.mongo import connect, ensure_indexes
from zapagent.store.seed import seed_store

logger = logging.getLogger("zapagent.bootstrap")

FUNCTION_NAME = "zapagent-webhook"
API_ID = "zapagent"
STAGE = "local"
LAMBDA_ROLE = "arn:aws:iam::000000000000:role/zapagent-webhook"


def build_lambda_zip() -> bytes:
    package_root = Path(zapagent.__file__).parent
    buffer = io.BytesIO()
    sources = [(package_root / "__init__.py", "zapagent/__init__.py")] + [
        (source, f"zapagent/webhook/{source.name}")
        for source in sorted((package_root / "webhook").glob("*.py"))
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in sources:
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, source.read_bytes())
    return buffer.getvalue()


def provision_bucket(s3: Any, bucket: str) -> None:
    try:
        s3.create_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in (
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        ):
            raise


def provision_queues(sqs: Any, settings: Settings) -> str:
    dlq_url = sqs.create_queue(QueueName=settings.inbound_dlq_name)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    queue_url = sqs.create_queue(QueueName=settings.inbound_queue_name)["QueueUrl"]
    sqs.set_queue_attributes(
        QueueUrl=queue_url,
        Attributes={
            "VisibilityTimeout": "60",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
        },
    )
    return queue_url


def provision_lambda(lambda_client: Any, settings: Settings, queue_url: str) -> str:
    environment = {
        "Variables": {
            "WHATSAPP_APP_SECRET": settings.whatsapp_app_secret,
            "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token,
            "INBOUND_QUEUE_URL": queue_url,
        }
    }
    code = build_lambda_zip()
    try:
        current = lambda_client.get_function(FunctionName=FUNCTION_NAME)["Configuration"]
    except lambda_client.exceptions.ResourceNotFoundException:
        lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Handler="zapagent.webhook.handler.handler",
            Role=LAMBDA_ROLE,
            Code={"ZipFile": code},
            Timeout=15,
            Environment=environment,
        )
    else:
        if current["CodeSha256"] != base64.b64encode(hashlib.sha256(code).digest()).decode():
            lambda_client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=code)
            lambda_client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
            logger.info("Código da Lambda atualizado")
        if current.get("Environment", {}).get("Variables") != environment["Variables"]:
            lambda_client.update_function_configuration(
                FunctionName=FUNCTION_NAME, Environment=environment
            )
            logger.info("Configuração da Lambda atualizada")
    lambda_client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
    lambda_client.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    return lambda_client.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]


def provision_api(apigateway: Any, region: str, function_arn: str) -> None:
    existing = {api["id"] for api in apigateway.get_rest_apis()["items"]}
    if API_ID not in existing:
        apigateway.create_rest_api(name="zapagent-webhook", tags={"_custom_id_": API_ID})
    resources = apigateway.get_resources(restApiId=API_ID)["items"]
    by_path = {resource["path"]: resource["id"] for resource in resources}
    if "/webhook" not in by_path:
        created = apigateway.create_resource(
            restApiId=API_ID, parentId=by_path["/"], pathPart="webhook"
        )
        by_path["/webhook"] = created["id"]
    uri = f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{function_arn}/invocations"
    for method in ("GET", "POST"):
        with contextlib.suppress(apigateway.exceptions.ConflictException):
            apigateway.put_method(
                restApiId=API_ID,
                resourceId=by_path["/webhook"],
                httpMethod=method,
                authorizationType="NONE",
            )
        apigateway.put_integration(
            restApiId=API_ID,
            resourceId=by_path["/webhook"],
            httpMethod=method,
            type="AWS_PROXY",
            integrationHttpMethod="POST",
            uri=uri,
        )
    apigateway.create_deployment(restApiId=API_ID, stageName=STAGE)


def ensure_replica_set(settings: Settings, timeout: float = 180) -> None:
    client = MongoClient(settings.mongo_direct_url, serverSelectionTimeoutMS=2000)
    deadline = time.monotonic() + timeout
    initiated = False
    while time.monotonic() < deadline:
        try:
            if client.admin.command("hello").get("isWritablePrimary"):
                logger.info("Replica set do MongoDB pronto")
                return
            if not initiated:
                client.admin.command(
                    "replSetInitiate",
                    {"_id": "rs0", "members": [{"_id": 0, "host": settings.mongo_replica_host}]},
                )
                initiated = True
        except OperationFailure as error:
            if error.code != 23:
                raise
            initiated = True
        except PyMongoError as error:
            logger.info("Aguardando MongoDB: %s", type(error).__name__)
        time.sleep(2)
    raise TimeoutError("MongoDB não ficou primário a tempo")


async def seed_database(settings: Settings) -> int:
    database = connect(settings.mongo_url, settings.mongo_db)
    await ensure_indexes(database)
    return await seed_store(database)


def main() -> None:
    settings = Settings()
    ensure_replica_set(settings)
    region = settings.aws_region
    provision_bucket(boto3.client("s3", region_name=region), settings.media_bucket)
    queue_url = provision_queues(boto3.client("sqs", region_name=region), settings)
    function_arn = provision_lambda(boto3.client("lambda", region_name=region), settings, queue_url)
    provision_api(boto3.client("apigateway", region_name=region), region, function_arn)
    logger.info("AWS local pronta: fila %s, função %s", queue_url, function_arn)
    orders = asyncio.run(seed_database(settings))
    logger.info("MongoDB pronto: %s pedido(s) de exemplo", orders)
    logger.info("Webhook: %s", settings.webhook_url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
