from decimal import Decimal

from shared.dynamodb import _dynamodb_value


def test_dynamodb_value_can_normalize_values_read_from_dynamodb() -> None:
    value = {
        "integer": Decimal("12"),
        "measurement": Decimal("18.6"),
        "nested": [Decimal("2.5")],
    }

    normalized = _dynamodb_value(value)

    assert normalized["integer"] == 12
    assert normalized["measurement"] == Decimal("18.6")
    assert normalized["nested"] == [Decimal("2.5")]
