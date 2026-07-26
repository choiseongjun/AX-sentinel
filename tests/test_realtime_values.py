import json
from decimal import Decimal

from shared.realtime import _json_default


def test_realtime_json_encodes_dynamodb_decimals() -> None:
    payload = {"whole": Decimal("12"), "fraction": Decimal("12.5")}

    encoded = json.dumps(payload, default=_json_default)

    assert json.loads(encoded) == {"whole": 12, "fraction": 12.5}
