import json
from functools import lru_cache
from typing import Any

import boto3

from shared.config import get_settings


class EventPublisher:
    def __init__(
        self,
        *,
        region_name: str,
        queue_name: str,
        topic_name: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._queue_name = queue_name
        self._topic_name = topic_name
        self._sqs = boto3.client("sqs", region_name=region_name, endpoint_url=endpoint_url)
        self._sns = boto3.client("sns", region_name=region_name, endpoint_url=endpoint_url)
        self._queue_url: str | None = None
        self._topic_arn: str | None = None

    def publish(self, event_type: str, payload: dict[str, Any], *, alert: bool = False) -> None:
        message = json.dumps(
            {"event_type": event_type, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if self._queue_url is None:
            self._queue_url = self._sqs.get_queue_url(QueueName=self._queue_name)["QueueUrl"]
        self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=message)

        if alert:
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


@lru_cache
def get_event_publisher() -> EventPublisher:
    settings = get_settings()
    return EventPublisher(
        region_name=settings.aws_region,
        queue_name=settings.events_queue,
        topic_name=settings.alerts_topic,
        endpoint_url=settings.aws_endpoint_url,
    )
