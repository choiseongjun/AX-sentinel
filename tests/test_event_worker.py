import asyncio
import json
from typing import Any

import pytest

from services.event_worker.app.main import EventWorker, parse_event_message


class MemoryRepository:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, Any]] = []

    def put(self, entity_type: str, entity_id: str, value: Any) -> None:
        self.items.append((entity_type, entity_id, value))


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
