import asyncio
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from functools import lru_cache
from typing import Any

import redis.asyncio as redis

from shared.config import get_settings

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _json_default(value: Any) -> int | float:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class RedisRealtimeBus:
    def __init__(self, url: str) -> None:
        self._redis = redis.from_url(url, decode_responses=True)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self._redis.publish(
            channel,
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_json_default,
            ),
        )

    async def listen(
        self,
        handlers: dict[str, MessageHandler],
        ready: asyncio.Event,
    ) -> None:
        async with self._redis.pubsub() as pubsub:
            await pubsub.subscribe(*handlers)
            ready.set()
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                handler = handlers.get(str(message["channel"]))
                if handler is not None:
                    await handler(json.loads(message["data"]))

    async def close(self) -> None:
        await self._redis.aclose()


@lru_cache
def get_realtime_bus() -> RedisRealtimeBus:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for the Redis WebSocket broker")
    return RedisRealtimeBus(settings.redis_url)
