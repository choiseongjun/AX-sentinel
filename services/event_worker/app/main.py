import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol
from uuid import uuid4

import boto3
from fastapi import Depends, Query
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from prometheus_client import Counter
from pydantic import BaseModel, ValidationError

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.concurrency import run_broker, run_database
from shared.config import get_settings
from shared.dynamodb import DynamoRepository, get_repository
from shared.events import KAFKA_DLQ_TOPIC, KAFKA_TOPICS, EventEnvelope

logger = logging.getLogger(__name__)

EVENTS_PROCESSED = Counter(
    "ax_sentinel_events_processed_total",
    "Domain events successfully processed",
    ["broker", "event_type", "result"],
)
EVENTS_FAILED = Counter(
    "ax_sentinel_events_failed_total",
    "Domain event processing attempts that failed",
    ["broker", "reason"],
)


class ProcessedEvent(BaseModel):
    id: str
    event_type: str
    result: str
    payload: dict[str, Any]
    receive_count: int = 1
    processed_at: datetime
    broker: str = "sqs"
    topic: str | None = None
    partition: int | None = None
    offset: int | None = None
    producer: str | None = None
    correlation_id: str | None = None


class WorkerStatus(BaseModel):
    running: bool
    broker: str
    consumer_group: str | None = None
    topics: list[str] = []
    queue_name: str | None = None
    approximate_messages: int = 0
    approximate_in_flight: int = 0


class Worker(Protocol):
    @property
    def running(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def status(self) -> WorkerStatus: ...


def parse_event_message(message: dict[str, Any]) -> tuple[EventEnvelope, int]:
    body = message.get("Body")
    if not isinstance(body, str):
        raise ValueError("SQS message body is missing")
    try:
        value = json.loads(body)
        if "producer" not in value:
            value["producer"] = "legacy-sqs"
        if "event_id" not in value and message.get("MessageId"):
            value["event_id"] = str(message["MessageId"])
        envelope = EventEnvelope.model_validate(value)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid AX Sentinel event envelope") from exc
    receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    return envelope, receive_count


class EventWorker:
    """Legacy SQS consumer retained for AWS compatibility."""

    known_event_types = {
        "telemetry.received",
        "incident.detected",
        "incident.status_changed",
        "analysis.completed",
        "document.registered",
        "approval.decided",
        "work_order.created",
        "work_order.completed",
        "feedback.submitted",
    }

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
        self._queue_url = await run_broker(
            lambda: self._sqs.get_queue_url(QueueName=self._queue_name)["QueueUrl"]
        )
        self._stopping.clear()
        self._task = asyncio.create_task(self._poll(), name="sqs-domain-event-worker")

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
            id=envelope.event_id,
            event_type=envelope.event_type,
            result=result,
            payload=envelope.payload,
            receive_count=receive_count,
            processed_at=datetime.now(UTC),
            broker="sqs",
            producer=envelope.producer,
            correlation_id=envelope.correlation_id,
        )
        await run_database(
            self._repository.put,
            "processed_event",
            envelope.event_id,
            event,
        )
        await run_broker(
            self._sqs.delete_message,
            QueueUrl=self._required_queue_url(),
            ReceiptHandle=receipt_handle,
        )
        EVENTS_PROCESSED.labels("sqs", envelope.event_type, result).inc()

    async def status(self) -> WorkerStatus:
        attributes = await run_broker(
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
            broker="sqs",
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
                messages = await run_broker(self._receive)
                for message in messages:
                    try:
                        await self.process_message(message)
                    except (ValueError, ValidationError) as exc:
                        EVENTS_FAILED.labels("sqs", "invalid_message").inc()
                        logger.warning("SQS event rejected and left for retry: %s", exc)
                    except Exception:
                        EVENTS_FAILED.labels("sqs", "processing_error").inc()
                        logger.exception("SQS event processing failed and will be retried")
            except asyncio.CancelledError:
                raise
            except Exception:
                EVENTS_FAILED.labels("sqs", "poll_error").inc()
                logger.exception("SQS polling failed")
                await asyncio.sleep(2)


class KafkaEventWorker:
    def __init__(
        self,
        *,
        repository: DynamoRepository,
        bootstrap_servers: str,
        consumer_group: str,
        topics: tuple[str, ...] = KAFKA_TOPICS,
        max_processing_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._bootstrap_servers = bootstrap_servers
        self._consumer_group = consumer_group
        self._topics = topics
        self._max_processing_attempts = max(1, max_processing_attempts)
        self._consumer: KafkaConsumer | None = None
        self._dlq_producer: KafkaProducer | None = None
        self._attempts: dict[tuple[str, int, int], int] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _create_consumer(self) -> KafkaConsumer:
        return KafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            client_id="ax-sentinel-event-worker",
            group_id=self._consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )

    def _create_dlq_producer(self) -> KafkaProducer:
        return KafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            client_id="ax-sentinel-event-worker-dlq",
            acks="all",
            retries=5,
            max_in_flight_requests_per_connection=1,
            value_serializer=lambda value: json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8"),
        )

    async def start(self) -> None:
        self._consumer = await run_broker(self._create_consumer)
        self._dlq_producer = await run_broker(self._create_dlq_producer)
        self._stopping.clear()
        self._task = asyncio.create_task(self._poll(), name="kafka-domain-event-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._consumer is not None:
            await run_broker(self._consumer.close)
            self._consumer = None
        if self._dlq_producer is not None:
            await run_broker(self._dlq_producer.close)
            self._dlq_producer = None

    def _required_consumer(self) -> KafkaConsumer:
        if self._consumer is None:
            raise RuntimeError("Kafka event worker has not started")
        return self._consumer

    def _poll_records(self) -> dict[Any, list[Any]]:
        return self._required_consumer().poll(timeout_ms=1000, max_records=100)

    def _seek_to_record(self, record: Any) -> None:
        self._required_consumer().seek(
            TopicPartition(record.topic, record.partition),
            record.offset,
        )

    async def process_record(self, record: Any) -> None:
        envelope = EventEnvelope.model_validate(record.value)
        existing = await run_database(
            self._repository.get,
            "processed_event",
            envelope.event_id,
        )
        result = "duplicate" if existing is not None else "processed"
        if existing is None:
            event = ProcessedEvent(
                id=envelope.event_id,
                event_type=envelope.event_type,
                result=result,
                payload=envelope.payload,
                processed_at=datetime.now(UTC),
                broker="kafka",
                topic=record.topic,
                partition=record.partition,
                offset=record.offset,
                producer=envelope.producer,
                correlation_id=envelope.correlation_id,
            )
            await run_database(
                self._repository.put,
                "processed_event",
                envelope.event_id,
                event,
            )
        EVENTS_PROCESSED.labels("kafka", envelope.event_type, result).inc()

    def _publish_dead_letter(self, key: str, value: dict[str, Any]) -> None:
        if self._dlq_producer is None:
            raise RuntimeError("Kafka DLQ producer has not started")
        self._dlq_producer.send(KAFKA_DLQ_TOPIC, key=key, value=value).get(timeout=10)

    async def _dead_letter(
        self,
        record: Any,
        error: Exception,
        attempts: int,
    ) -> None:
        original = record.value
        original_envelope = original if isinstance(original, dict) else {}
        dead_letter_id = f"dlq-{record.topic}-{record.partition}-{record.offset}"
        message = EventEnvelope(
            event_id=str(uuid4()),
            event_type="event.processing_failed",
            producer="event-worker",
            correlation_id=str(
                original_envelope.get("correlation_id") or uuid4()
            ),
            causation_id=original_envelope.get("event_id"),
            payload={
                "source_topic": record.topic,
                "source_partition": record.partition,
                "source_offset": record.offset,
                "original_key": (
                    record.key.decode("utf-8", errors="replace")
                    if isinstance(getattr(record, "key", None), bytes)
                    else getattr(record, "key", None)
                ),
                "original_value": original,
                "error_type": type(error).__name__,
                "error_message": str(error)[:1000],
                "attempts": attempts,
            },
        ).model_dump(mode="json")
        await run_broker(self._publish_dead_letter, dead_letter_id, message)
        processed = ProcessedEvent(
            id=dead_letter_id,
            event_type="event.processing_failed",
            result="dead_lettered",
            payload=message["payload"],
            receive_count=attempts,
            processed_at=datetime.now(UTC),
            broker="kafka",
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            producer="event-worker",
            correlation_id=message["correlation_id"],
        )
        await run_database(
            self._repository.put,
            "processed_event",
            dead_letter_id,
            processed,
        )
        EVENTS_PROCESSED.labels(
            "kafka",
            "event.processing_failed",
            "dead_lettered",
        ).inc()

    async def process_record_with_retry(self, record: Any) -> bool:
        record_key = (record.topic, record.partition, record.offset)
        try:
            await self.process_record(record)
            self._attempts.pop(record_key, None)
            return True
        except Exception as exc:
            attempts = self._attempts.get(record_key, 0) + 1
            self._attempts[record_key] = attempts
            EVENTS_FAILED.labels("kafka", "processing_error").inc()
            if attempts < self._max_processing_attempts:
                logger.warning(
                    "Kafka event processing failed (%d/%d), offset not committed: %s",
                    attempts,
                    self._max_processing_attempts,
                    exc,
                )
                return False
            await self._dead_letter(record, exc, attempts)
            self._attempts.pop(record_key, None)
            logger.error(
                "Kafka event moved to %s after %d attempts: %s",
                KAFKA_DLQ_TOPIC,
                attempts,
                exc,
            )
            return True

    async def status(self) -> WorkerStatus:
        return WorkerStatus(
            running=self.running,
            broker="kafka",
            consumer_group=self._consumer_group,
            topics=list(self._topics),
        )

    async def _poll(self) -> None:
        while not self._stopping.is_set():
            try:
                batches = await run_broker(self._poll_records)
                processed_any = False
                batch_failed = False
                for records in batches.values():
                    for record in records:
                        handled = await self.process_record_with_retry(record)
                        if not handled:
                            await run_broker(self._seek_to_record, record)
                            batch_failed = True
                            break
                        processed_any = True
                if processed_any and not batch_failed:
                    await run_broker(self._required_consumer().commit)
                elif batch_failed:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except (ValueError, ValidationError) as exc:
                EVENTS_FAILED.labels("kafka", "invalid_message").inc()
                logger.warning("Kafka event rejected without offset commit: %s", exc)
                await asyncio.sleep(1)
            except Exception:
                EVENTS_FAILED.labels("kafka", "processing_error").inc()
                logger.exception("Kafka event processing failed without offset commit")
                await asyncio.sleep(2)


settings = get_settings()
if settings.event_bus in {"kafka", "dual"}:
    event_worker: Worker = KafkaEventWorker(
        repository=get_repository(),
        bootstrap_servers=settings.kafka_bootstrap_servers,
        consumer_group=settings.kafka_consumer_group,
        max_processing_attempts=settings.kafka_max_processing_attempts,
    )
else:
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
    values = await run_database(get_repository().list, "processed_event")
    events = [ProcessedEvent.model_validate(value) for value in values]
    events.sort(key=lambda item: item.processed_at, reverse=True)
    return events[:limit]
