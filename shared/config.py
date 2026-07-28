from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    aws_region: str = "ap-northeast-2"
    aws_endpoint_url: str | None = None
    dynamodb_table: str = "axsentinel-domain"
    events_queue: str = "axsentinel-events"
    events_dlq: str = "axsentinel-events-dlq"
    event_wait_time_seconds: int = 10
    event_bus: str = "disabled"
    service_name: str = "ax-sentinel"
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_consumer_group: str = "ax-sentinel-event-worker-v1"
    kafka_publish_timeout_seconds: float = 10
    kafka_max_processing_attempts: int = 3
    alerts_topic: str = "axsentinel-alerts"
    websocket_broker: str = "memory"
    redis_url: str | None = None
    log_level: str = "INFO"
    auth_mode: str = "disabled"
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    oidc_client_id: str | None = None
    asset_service_url: str | None = None
    incident_service_url: str | None = None
    analysis_service_url: str | None = None
    knowledge_service_url: str | None = None
    work_order_service_url: str | None = None
    ai_provider: str = "mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "hoangquan456/qwen3-nothink:4b"
    ollama_timeout_seconds: float = 180
    bedrock_model_id: str | None = None
    bedrock_guardrail_id: str | None = None
    bedrock_guardrail_version: str | None = None
    documents_bucket: str = "axsentinel-local"
    rag_provider: str = "local"
    bedrock_knowledge_base_id: str | None = None
    bedrock_data_source_id: str | None = None
    database_thread_workers: int = 16
    broker_thread_workers: int = 8
    ai_thread_workers: int = 4
    authentication_thread_workers: int = 8
    storage_thread_workers: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
