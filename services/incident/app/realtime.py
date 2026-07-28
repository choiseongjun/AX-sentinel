import asyncio
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from shared.realtime import RedisRealtimeBus

from .application import INCIDENT_CHANNEL, TELEMETRY_CHANNEL


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(
        self,
        websocket: WebSocket,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, model: BaseModel | dict[str, object]) -> None:
        message = (
            model.model_dump(mode="json")
            if isinstance(model, BaseModel)
            else model
        )
        disconnected: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json(message)
            except (OSError, RuntimeError, WebSocketDisconnect):
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)


class RealtimeHub:
    """Facade for in-memory WebSockets and Redis cross-pod fan-out."""

    def __init__(
        self,
        *,
        broker: str,
        redis_bus: RedisRealtimeBus | None = None,
    ) -> None:
        self._broker = broker
        self._redis_bus = redis_bus
        self.telemetry = WebSocketConnectionManager()
        self.incidents = WebSocketConnectionManager()
        self._listener_task: asyncio.Task[None] | None = None

    async def publish(self, channel: str, model: BaseModel) -> None:
        if self._broker == "redis":
            if self._redis_bus is None:
                raise RuntimeError("Redis realtime bus is not configured")
            await self._redis_bus.publish(channel, model.model_dump(mode="json"))
            return
        await self._manager_for(channel).broadcast(model)

    def _manager_for(self, channel: str) -> WebSocketConnectionManager:
        if channel == TELEMETRY_CHANNEL:
            return self.telemetry
        if channel == INCIDENT_CHANNEL:
            return self.incidents
        raise ValueError(f"Unknown realtime channel: {channel}")

    async def start(self) -> None:
        if self._broker != "redis":
            return
        if self._redis_bus is None:
            raise RuntimeError("Redis realtime bus is not configured")

        ready = asyncio.Event()
        self._listener_task = asyncio.create_task(
            self._redis_bus.listen(
                {
                    TELEMETRY_CHANNEL: self.telemetry.broadcast,
                    INCIDENT_CHANNEL: self.incidents.broadcast,
                },
                ready,
            ),
            name="incident-realtime-listener",
        )
        await asyncio.wait_for(ready.wait(), timeout=10)

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        if self._broker == "redis" and self._redis_bus is not None:
            await self._redis_bus.close()
