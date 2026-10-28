from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)

    mongo_url: str = "mongodb://mongo:27017/?replicaSet=rs0"
    mongo_db: str = "zapagent"
    mongo_direct_url: str = "mongodb://mongo:27017/?directConnection=true"
    mongo_replica_host: str = "mongo:27017"

    aws_region: str = "us-east-1"
    inbound_queue_name: str = "zapagent-inbound"
    inbound_dlq_name: str = "zapagent-inbound-dlq"
    media_bucket: str = "zapagent-media"
    webhook_url: str = "http://localstack:4566/_aws/execute-api/zapagent/local/webhook"

    graph_base_url: str = "http://api:8000/graph"
    graph_api_version: str = "v21.0"
    graph_token: str = "simulator-token"
    phone_number_id: str = "100000000000001"
    whatsapp_app_secret: str = "simulator-app-secret"
    whatsapp_verify_token: str = "simulator-verify-token"

    mcp_server_url: str = "http://mcp-server:8001/mcp"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001

    llm_base_url: str = "http://ollama:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"
    llm_temperature: float | None = None
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: float = 60.0
    agent_max_steps: int = 6
    history_limit: int = 20
    store_name: str = "Loja Aurora"
