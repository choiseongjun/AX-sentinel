import asyncio
import contextvars
import threading

from shared.concurrency import (
    run_ai,
    run_authentication,
    run_broker,
    run_database,
    run_storage,
    shutdown_blocking_executors,
)


def test_blocking_workloads_use_dedicated_thread_pools() -> None:
    def current_thread_name() -> str:
        return threading.current_thread().name

    async def scenario() -> list[str]:
        return await asyncio.gather(
            run_database(current_thread_name),
            run_broker(current_thread_name),
            run_ai(current_thread_name),
            run_authentication(current_thread_name),
            run_storage(current_thread_name),
        )

    try:
        thread_names = asyncio.run(scenario())
    finally:
        shutdown_blocking_executors()

    assert thread_names[0].startswith("ax-database")
    assert thread_names[1].startswith("ax-broker")
    assert thread_names[2].startswith("ax-ai")
    assert thread_names[3].startswith("ax-authentication")
    assert thread_names[4].startswith("ax-storage")
    assert len({name.rsplit("_", 1)[0] for name in thread_names}) == 5


def test_blocking_call_does_not_stall_event_loop() -> None:
    release = threading.Event()
    started = threading.Event()

    def blocking_call() -> str:
        started.set()
        release.wait(timeout=1)
        return "done"

    async def scenario() -> None:
        task = asyncio.create_task(run_database(blocking_call))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
        assert not task.done()
        release.set()
        assert await asyncio.wait_for(task, timeout=1) == "done"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        shutdown_blocking_executors()


def test_request_context_is_propagated_to_pool_thread() -> None:
    correlation_id = contextvars.ContextVar[str]("correlation_id")

    async def scenario() -> str:
        correlation_id.set("incident-123")
        return await run_broker(correlation_id.get)

    try:
        assert asyncio.run(scenario()) == "incident-123"
    finally:
        shutdown_blocking_executors()
