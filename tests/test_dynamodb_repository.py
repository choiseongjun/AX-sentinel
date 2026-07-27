import pytest
from botocore.exceptions import ClientError

from shared.dynamodb import ConcurrentUpdateError, DynamoRepository


class FakeTable:
    def __init__(self) -> None:
        self.query_requests: list[dict] = []
        self.current: dict | None = None
        self.fail_condition = False

    def query(self, **request):
        self.query_requests.append(request)
        return {
            "Items": [{"data": {"id": "INC-2"}}, {"data": {"id": "INC-1"}}],
            "LastEvaluatedKey": {"pk": "INCIDENT#INC-1", "sk": "METADATA"},
        }

    def get_item(self, **_request):
        return {"Item": self.current} if self.current else {}

    def put_item(self, **request):
        if self.fail_condition:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "condition failed",
                    }
                },
                "PutItem",
            )
        self.current = request["Item"]


def repository_with(table: FakeTable) -> DynamoRepository:
    repository = DynamoRepository.__new__(DynamoRepository)
    repository._table = table
    return repository


def test_list_page_uses_gsi_query_and_cursor() -> None:
    table = FakeTable()
    repository = repository_with(table)
    cursor = {"pk": "INCIDENT#INC-3", "sk": "METADATA"}

    items, next_cursor = repository.list_page("incident", limit=500, cursor=cursor)

    assert items == [{"id": "INC-2"}, {"id": "INC-1"}]
    assert next_cursor == {"pk": "INCIDENT#INC-1", "sk": "METADATA"}
    request = table.query_requests[0]
    assert request["IndexName"] == "entity_type-updated_at-index"
    assert request["ScanIndexForward"] is False
    assert request["Limit"] == 200
    assert request["ExclusiveStartKey"] == cursor


def test_put_increments_version_and_detects_concurrent_write() -> None:
    table = FakeTable()
    repository = repository_with(table)

    repository.put("incident", "INC-1", {"status": "detected"})
    assert table.current is not None
    assert table.current["version"] == 1

    repository.put("incident", "INC-1", {"status": "analyzing"})
    assert table.current["version"] == 2

    table.fail_condition = True
    with pytest.raises(ConcurrentUpdateError):
        repository.put("incident", "INC-1", {"status": "resolved"})
