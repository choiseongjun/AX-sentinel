import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any

import boto3
from fastapi import Depends, Query
from prometheus_client import Counter
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.config import get_settings
from shared.dynamodb import DynamoRepository, get_repository

logger = logging.getLogger(__name__)

EVENTS_PROCESSED = Counter(
    "ax_sentinel_events_processed_total",
    "Domain events successfully processed",
    ["event_type", "result"],
)
EVENTS_FAILED = Counter(
    "ax_sentinel_events_failed_total",
    "Domain event processing attempts that failed",
    ["reason"],
)


class EventEnvelope(BaseModel):
    event_type: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]


class ProcessedEvent(BaseModel):
    id: str
    event_type: str
    result: str
    payload: dict[str, Any]
    receive_count: int
    processed_at: datetime


class WorkerStatus(BaseModel):
    running: bool
    queue_name: str
    approximate_messages: int
    approximate_in_flight: int


def parse_event_message(message: dict[str, Any]) -> tuple[EventEnvelope, int]:
    body = message.get("Body")
    if not isinstance(body, str):
        raise ValueError("SQS message body is missing")
    try:
        envelope = EventEnvelope.model_validate_json(body)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid AX Sentinel event envelope") from exc
    receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    return envelope, receive_count


class EventWorker:
    known_event_types = {"incident.detected"}

    def __init__(
        self,
        *,
        repository: DynamoRepository,
        sqs_client: Any,
        queue_name: str,
        wait_time_seconds: int,
    ) -> None:
        self._repository = repository
        self._sqs = sqs_client
        self._queue_name = queue_name
        self._wait_time_seconds = wait_time_seconds
        self._queue_url: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        self._queue_url = await run_in_threadpool(
            lambda: self._sqs.get_queue_url(QueueName=self._queue_name)["QueueUrl"]
        )
        self._stopping.clear()
        self._task = asyncio.create_task(self._poll(), name="domain-event-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process_message(self, message: dict[str, Any]) -> None:
        envelope, receive_count = parse_event_message(message)
        message_id = str(message.get("MessageId", "")).strip()
        receipt_handle = str(message.get("ReceiptHandle", "")).strip()
        if not message_id or not receipt_handle:
            raise ValueError("SQS message identifiers are missing")

        result = "processed" if envelope.event_type in self.known_event_types else "ignored"
        event = ProcessedEvent(
            id=message_id,
            event_type=envelope.event_type,
            result=result,
            payload=envelope.payload,
            receive_count=receive_count,
            processed_at=datetime.now(UTC),
        )
        await run_in_threadpool(
            self._repository.put,
            "processed_event",
            message_id,
            event,
        )
        await run_in_threadpool(
            self._sqs.delete_message,
            QueueUrl=self._required_queue_url(),
            ReceiptHandle=receipt_handle,
        )
        EVENTS_PROCESSED.labels(envelope.event_type, result).inc()

    async def status(self) -> WorkerStatus:
        attributes = await run_in_threadpool(
            self._sqs.get_queue_attributes,
            QueueUrl=self._required_queue_url(),
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        values = attributes.get("Attributes", {})
        return WorkerStatus(
            running=self.running,
            queue_name=self._queue_name,
            approximate_messages=int(values.get("ApproximateNumberOfMessages", "0")),
            approximate_in_flight=int(
                values.get("ApproximateNumberOfMessagesNotVisible", "0")
            ),
        )

    def _required_queue_url(self) -> str:
        if self._queue_url is None:
            raise RuntimeError("Event worker has not started")
        return self._queue_url

    def _receive(self) -> list[dict[str, Any]]:
        response = self._sqs.receive_message(
            QueueUrl=self._required_queue_url(),
            MaxNumberOfMessages=10,
            WaitTimeSeconds=self._wait_time_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        return response.get("Messages", [])

    async def _poll(self) -> None:
        while not self._stopping.is_set():
            try:
                messages = await run_in_threadpool(self._receive)
                for message in messages:
                    try:
                        await self.process_message(message)
                    except (ValueError, ValidationError) as exc:
                        EVENTS_FAILED.labels("invalid_message").inc()
                        logger.warning("Event rejected and left for retry: %s", exc)
                    except Exception:
                        EVENTS_FAILED.labels("processing_error").inc()
                        logger.exception("Event processing failed and will be retried")
            except asyncio.CancelledError:
                raise
            except Exception:
                EVENTS_FAILED.labels("poll_error").inc()
                logger.exception("SQS polling failed")
                await asyncio.sleep(2)


settings = get_settings()
event_worker = EventWorker(
    repository=get_repository(),
    sqs_client=boto3.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ),
    queue_name=settings.events_queue,
    wait_time_seconds=settings.event_wait_time_seconds,
)

app = create_app(
    "event-worker",
    startup=event_worker.start,
    shutdown=event_worker.stop,
)


@app.get(
    "/api/v1/events/worker/status",
    response_model=WorkerStatus,
    tags=["events"],
)
async def worker_status(
    _: Annotated[
        Principal,
        Depends(require_roles(Role.SYSTEM_ADMIN, Role.OPERATOR_MANAGER)),
    ],
) -> WorkerStatus:
    return await event_worker.status()


@app.get(
    "/api/v1/events/processed",
    response_model=list[ProcessedEvent],
    tags=["events"],
)
async def processed_events(
    _: Annotated[
        Principal,
        Depends(require_roles(Role.SYSTEM_ADMIN, Role.OPERATOR_MANAGER)),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ProcessedEvent]:
    values = await run_in_threadpool(get_repository().list, "processed_event")
    events = [ProcessedEvent.model_validate(value) for value in values]
    events.sort(key=lambda item: item.processed_at, reverse=True)
    return events[:limit]
