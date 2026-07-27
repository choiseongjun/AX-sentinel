import asyncio
import json
from typing import Any

import pytest

from services.event_worker.app.main import EventWorker, KafkaEventWorker, parse_event_message
from shared.events import EventEnvelope, topic_for


class MemoryRepository:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, Any]] = []

    def put(self, entity_type: str, entity_id: str, value: Any) -> None:
        self.items.append((entity_type, entity_id, value))

    def get(self, entity_type: str, entity_id: str) -> Any | None:
        return next(
            (
                value
                for stored_type, stored_id, value in reversed(self.items)
                if stored_type == entity_type and stored_id == entity_id
            ),
            None,
        )


class FakeSqs:
    def __init__(self) -> None:
        self.deleted: list[dict[str, str]] = []

    def delete_message(self, **kwargs: str) -> None:
        self.deleted.append(kwargs)


def sqs_message(body: str) -> dict[str, Any]:
    return {
        "MessageId": "message-1",
        "ReceiptHandle": "receipt-1",
        "Body": body,
        "Attributes": {"ApproximateReceiveCount": "2"},
    }


def test_parse_event_message_reads_receive_count() -> None:
    envelope, receive_count = parse_event_message(
        sqs_message(json.dumps({"event_type": "incident.detected", "payload": {"id": "1"}}))
    )

    assert envelope.event_type == "incident.detected"
    assert receive_count == 2


def test_parse_event_message_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="Invalid AX Sentinel event envelope"):
        parse_event_message(sqs_message("not-json"))


def test_worker_persists_before_deleting_message() -> None:
    repository = MemoryRepository()
    sqs = FakeSqs()
    worker = EventWorker(
        repository=repository,  # type: ignore[arg-type]
        sqs_client=sqs,
        queue_name="events",
        wait_time_seconds=0,
    )
    worker._queue_url = "http://sqs/events"

    asyncio.run(
        worker.process_message(
            sqs_message(
                json.dumps(
                    {
                        "event_type": "incident.detected",
                        "payload": {"incident_id": "incident-1"},
                    }
                )
            )
        )
    )

    assert repository.items[0][0:2] == ("processed_event", "message-1")
    assert sqs.deleted == [
        {"QueueUrl": "http://sqs/events", "ReceiptHandle": "receipt-1"}
    ]


def test_topic_mapping_uses_bounded_domain_topics() -> None:
    assert topic_for("telemetry.received") == "ax.telemetry.events.v1"
    assert topic_for("incident.detected") == "ax.incident.events.v1"
    assert topic_for("analysis.completed") == "ax.analysis.events.v1"
    assert topic_for("unknown.event") == "ax.audit.events.v1"


def test_kafka_worker_persists_envelope_with_offset() -> None:
    repository = MemoryRepository()
    worker = KafkaEventWorker(
        repository=repository,  # type: ignore[arg-type]
        bootstrap_servers="unused:9092",
        consumer_group="test-group",
    )
    envelope = EventEnvelope(
        event_id="event-1",
        event_type="incident.detected",
        producer="incident-service",
        correlation_id="correlation-1",
        payload={"incident_id": "incident-1"},
    )
    record = type(
        "Record",
        (),
        {
            "value": envelope.model_dump(mode="json"),
            "topic": "ax.incident.events.v1",
            "partition": 2,
            "offset": 41,
        },
    )()

    asyncio.run(worker.process_record(record))
    asyncio.run(worker.process_record(record))

    assert len(repository.items) == 1
    processed = repository.items[0][2]
    assert processed.id == "event-1"
    assert processed.broker == "kafka"
    assert processed.partition == 2
    assert processed.offset == 41
