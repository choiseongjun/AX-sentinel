from typing import Any

from pydantic import BaseModel

from shared.concurrency import run_broker, run_database
from shared.dynamodb import DynamoRepository
from shared.events import EventPublisher


class AsyncDynamoRepository:
    """Async adapter that keeps boto3 outside the application layer."""

    def __init__(self, repository: DynamoRepository) -> None:
        self._repository = repository

    async def put(
        self,
        entity_type: str,
        entity_id: str,
        value: BaseModel | dict[str, Any],
    ) -> None:
        await run_database(
            self._repository.put,
            entity_type,
            entity_id,
            value,
        )

    async def get(
        self,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        return await run_database(
            self._repository.get,
            entity_type,
            entity_id,
        )

    async def list(self, entity_type: str) -> list[dict[str, Any]]:
        return await run_database(self._repository.list, entity_type)


class AsyncDomainEventPublisher:
    """Async adapter that isolates the blocking Kafka/SNS publisher."""

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        key: str | None = None,
        actor_id: str | None = None,
        alert: bool = False,
    ) -> None:
        await run_broker(
            self._publisher.publish,
            event_type,
            payload,
            key=key,
            actor_id=actor_id,
            alert=alert,
        )
