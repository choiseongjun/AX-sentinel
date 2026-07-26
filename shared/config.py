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
    alerts_topic: str = "axsentinel-alerts"
    websocket_broker: str = "memory"
    redis_url: str | None = None
    log_level: str = "INFO"
    auth_mode: str = "disabled"
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    ai_provider: str = "mock"
    bedrock_model_id: str | None = None
    bedrock_guardrail_id: str | None = None
    bedrock_guardrail_version: str | None = None
    documents_bucket: str = "axsentinel-local"
    rag_provider: str = "local"
    bedrock_knowledge_base_id: str | None = None
    bedrock_data_source_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
