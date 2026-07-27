import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

import boto3
from kafka import KafkaProducer
from pydantic import BaseModel, Field

from shared.config import get_settings

TOPIC_BY_PREFIX = {
    "telemetry.": "ax.telemetry.events.v1",
    "incident.": "ax.incident.events.v1",
    "analysis.": "ax.analysis.events.v1",
    "document.": "ax.knowledge.events.v1",
    "approval.": "ax.work-order.events.v1",
    "work_order.": "ax.work-order.events.v1",
    "feedback.": "ax.feedback.events.v1",
    "evaluation.": "ax.feedback.events.v1",
}

KAFKA_TOPICS = tuple(dict.fromkeys([*TOPIC_BY_PREFIX.values(), "ax.audit.events.v1"]))


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str = Field(min_length=1, max_length=200)
    event_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    actor_id: str | None = None
    payload: dict[str, Any]


def topic_for(event_type: str) -> str:
    return next(
        (
            topic
            for prefix, topic in TOPIC_BY_PREFIX.items()
            if event_type.startswith(prefix)
        ),
        "ax.audit.events.v1",
    )


class EventPublisher:
    """Publish versioned domain events to Kafka, with optional SQS compatibility."""

    def __init__(
        self,
        *,
        service_name: str,
        event_bus: str,
        kafka_bootstrap_servers: str,
        kafka_publish_timeout_seconds: float,
        region_name: str,
        queue_name: str,
        topic_name: str,
        endpoint_url: str | None = None,
    ) -> None:
        if event_bus not in {"disabled", "kafka", "sqs", "dual"}:
            raise ValueError(f"Unsupported event bus: {event_bus}")
        self._service_name = service_name
        self._event_bus = event_bus
        self._kafka_bootstrap_servers = kafka_bootstrap_servers
        self._kafka_publish_timeout_seconds = kafka_publish_timeout_seconds
        self._kafka: KafkaProducer | None = None
        self._queue_name = queue_name
        self._topic_name = topic_name
        self._sqs = (
            boto3.client("sqs", region_name=region_name, endpoint_url=endpoint_url)
            if event_bus in {"sqs", "dual"}
            else None
        )
        self._sns = boto3.client(
            "sns",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._queue_url: str | None = None
        self._topic_arn: str | None = None

    def _kafka_producer(self) -> KafkaProducer:
        if self._kafka is None:
            self._kafka = KafkaProducer(
                bootstrap_servers=self._kafka_bootstrap_servers,
                client_id=self._service_name,
                acks="all",
                retries=5,
                max_in_flight_requests_per_connection=1,
                value_serializer=lambda value: json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
                key_serializer=lambda value: value.encode("utf-8"),
            )
        return self._kafka

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        key: str | None = None,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        alert: bool = False,
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            event_type=event_type,
            producer=self._service_name,
            correlation_id=correlation_id or str(uuid4()),
            causation_id=causation_id,
            actor_id=actor_id,
            payload=payload,
        )
        serialized = envelope.model_dump(mode="json")

        if self._event_bus in {"kafka", "dual"}:
            message_key = key or str(
                payload.get("incident_id")
                or payload.get("equipment_id")
                or payload.get("id")
                or envelope.event_id
            )
            self._kafka_producer().send(
                topic_for(event_type),
                key=message_key,
                value=serialized,
                headers=[
                    ("event_type", event_type.encode("utf-8")),
                    ("event_version", b"1"),
                ],
            ).get(timeout=self._kafka_publish_timeout_seconds)

        message = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
        if self._event_bus in {"sqs", "dual"}:
            if self._sqs is None:
                raise RuntimeError("SQS publisher is not configured")
            if self._queue_url is None:
                self._queue_url = self._sqs.get_queue_url(
                    QueueName=self._queue_name
                )["QueueUrl"]
            self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=message)

        if alert and self._event_bus != "disabled":
            if self._topic_arn is None:
                topics = self._sns.list_topics().get("Topics", [])
                self._topic_arn = next(
                    (
                        topic["TopicArn"]
                        for topic in topics
                        if topic["TopicArn"].rsplit(":", 1)[-1] == self._topic_name
                    ),
                    None,
                )
                if self._topic_arn is None:
                    raise RuntimeError(f"SNS topic not found: {self._topic_name}")
            self._sns.publish(
                TopicArn=self._topic_arn,
                Subject=f"AX Sentinel: {event_type}",
                Message=message,
            )
        return envelope

    def close(self) -> None:
        if self._kafka is not None:
            self._kafka.flush(timeout=self._kafka_publish_timeout_seconds)
            self._kafka.close(timeout=self._kafka_publish_timeout_seconds)
            self._kafka = None


@lru_cache
def get_event_publisher() -> EventPublisher:
    settings = get_settings()
    return EventPublisher(
        service_name=settings.service_name,
        event_bus=settings.event_bus,
        kafka_bootstrap_servers=settings.kafka_bootstrap_servers,
        kafka_publish_timeout_seconds=settings.kafka_publish_timeout_seconds,
        region_name=settings.aws_region,
        queue_name=settings.events_queue,
        topic_name=settings.alerts_topic,
        endpoint_url=settings.aws_endpoint_url,
    )
