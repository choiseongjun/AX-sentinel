from typing import Any, Protocol

from pydantic import BaseModel


class EntityRepository(Protocol):
    async def put(
        self,
        entity_type: str,
        entity_id: str,
        value: BaseModel | dict[str, Any],
    ) -> None: ...

    async def get(
        self,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None: ...

    async def list(self, entity_type: str) -> list[dict[str, Any]]: ...


class DomainEventPublisher(Protocol):
    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        key: str | None = None,
        actor_id: str | None = None,
        alert: bool = False,
    ) -> None: ...


class RealtimePublisher(Protocol):
    async def publish(self, channel: str, model: BaseModel) -> None: ...
