import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from pydantic import BaseModel

from shared.config import get_settings


def _dynamodb_value(value: Any) -> Any:
    """Convert JSON-compatible values into DynamoDB-compatible values."""
    def json_default(item: Any) -> int | float:
        if isinstance(item, Decimal):
            return int(item) if item == item.to_integral_value() else float(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.loads(json.dumps(value, default=json_default), parse_float=Decimal)


class DynamoRepository:
    """Small single-table repository shared by the initial service APIs."""

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
        self._table.put_item(
            Item={
                "pk": f"{entity_type.upper()}#{entity_id}",
                "sk": "METADATA",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "updated_at": now,
                "data": _dynamodb_value(data),
            }
        )

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

    def list(self, entity_type: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {
            "FilterExpression": Attr("entity_type").eq(entity_type),
        }

        while True:
            response = self._table.scan(**request)
            items.extend(item["data"] for item in response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            request["ExclusiveStartKey"] = last_key

        return items


@lru_cache
def get_repository() -> DynamoRepository:
    settings = get_settings()
    return DynamoRepository(
        table_name=settings.dynamodb_table,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
