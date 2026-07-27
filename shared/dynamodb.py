import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel

from shared.config import get_settings


def _dynamodb_value(value: Any) -> Any:
    """Convert JSON-compatible values into DynamoDB-compatible values."""
    def json_default(item: Any) -> int | float:
        if isinstance(item, Decimal):
            return int(item) if item == item.to_integral_value() else float(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.loads(json.dumps(value, default=json_default), parse_float=Decimal)


class ConcurrentUpdateError(RuntimeError):
    """Raised when another writer changed an entity during an update."""


class DynamoRepository:
    """Repository for one service-owned DynamoDB table."""

    def __init__(
        self,
        *,
        table_name: str,
        region_name: str,
        endpoint_url: str | None = None,
    ) -> None:
        dynamodb = boto3.resource(
            "dynamodb",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        self._table = dynamodb.Table(table_name)

    def put(self, entity_type: str, entity_id: str, value: BaseModel | dict[str, Any]) -> None:
        data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        now = datetime.now(UTC).isoformat()
        key = {
            "pk": f"{entity_type.upper()}#{entity_id}",
            "sk": "METADATA",
        }
        current = self._table.get_item(Key=key, ConsistentRead=True).get("Item")
        current_version = int(current.get("version", 0)) if current else 0
        item = key | {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "updated_at": now,
            "version": current_version + 1,
            "data": _dynamodb_value(data),
        }
        try:
            if current is None:
                self._table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(pk)",
                )
            else:
                self._table.put_item(
                    Item=item,
                    ConditionExpression="#version = :expected_version",
                    ExpressionAttributeNames={"#version": "version"},
                    ExpressionAttributeValues={":expected_version": current_version},
                )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConcurrentUpdateError(
                    f"{entity_type}/{entity_id} was updated concurrently"
                ) from error
            raise

    def get(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={
                "pk": f"{entity_type.upper()}#{entity_id}",
                "sk": "METADATA",
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        return item["data"] if item else None

    def list_page(
        self,
        entity_type: str,
        *,
        limit: int = 100,
        cursor: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        request: dict[str, Any] = {
            "IndexName": "entity_type-updated_at-index",
            "KeyConditionExpression": Key("entity_type").eq(entity_type),
            "ScanIndexForward": False,
            "Limit": min(max(limit, 1), 200),
        }
        if cursor:
            request["ExclusiveStartKey"] = cursor
        response = self._table.query(**request)
        return (
            [item["data"] for item in response.get("Items", [])],
            response.get("LastEvaluatedKey"),
        )

    def list(self, entity_type: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: dict[str, Any] | None = None
        while True:
            page, cursor = self.list_page(entity_type, limit=200, cursor=cursor)
            items.extend(page)
            if cursor is None:
                break

        return items


@lru_cache
def get_repository() -> DynamoRepository:
    settings = get_settings()
    return DynamoRepository(
        table_name=settings.dynamodb_table,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
