import asyncio
import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from functools import partial
from threading import Lock

from shared.config import get_settings


class BlockingPool(StrEnum):
    DATABASE = "database"
    BROKER = "broker"
    AI = "ai"
    AUTHENTICATION = "authentication"
    STORAGE = "storage"


_executors: dict[BlockingPool, ThreadPoolExecutor] = {}
_executors_lock = Lock()


def _worker_count(pool: BlockingPool) -> int:
    settings = get_settings()
    workers = {
        BlockingPool.DATABASE: settings.database_thread_workers,
        BlockingPool.BROKER: settings.broker_thread_workers,
        BlockingPool.AI: settings.ai_thread_workers,
        BlockingPool.AUTHENTICATION: settings.authentication_thread_workers,
        BlockingPool.STORAGE: settings.storage_thread_workers,
    }[pool]
    return max(workers, 1)


def _get_executor(pool: BlockingPool) -> ThreadPoolExecutor:
    with _executors_lock:
        executor = _executors.get(pool)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=_worker_count(pool),
                thread_name_prefix=f"ax-{pool.value}",
            )
            _executors[pool] = executor
        return executor


async def run_blocking[**P, R](
    pool: BlockingPool,
    function: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Run a synchronous call outside the event loop in a workload-specific pool."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = partial(function, *args, **kwargs)
    return await loop.run_in_executor(_get_executor(pool), context.run, call)


async def run_database[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    return await run_blocking(BlockingPool.DATABASE, function, *args, **kwargs)


async def run_broker[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    return await run_blocking(BlockingPool.BROKER, function, *args, **kwargs)


async def run_ai[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    return await run_blocking(BlockingPool.AI, function, *args, **kwargs)


async def run_authentication[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    return await run_blocking(BlockingPool.AUTHENTICATION, function, *args, **kwargs)


async def run_storage[**P, R](
    function: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    return await run_blocking(BlockingPool.STORAGE, function, *args, **kwargs)


def shutdown_blocking_executors() -> None:
    """Stop pool threads during application shutdown without blocking the event loop."""
    with _executors_lock:
        executors = list(_executors.values())
        _executors.clear()
    for executor in executors:
        executor.shutdown(wait=False, cancel_futures=True)
