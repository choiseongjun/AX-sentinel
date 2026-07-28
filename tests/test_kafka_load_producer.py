import importlib.util
import io
import json
import random
from pathlib import Path
from types import ModuleType


def load_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "kafka-load-producer.py"
    spec = importlib.util.spec_from_file_location("kafka_load_producer", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_producer_creates_valid_telemetry_envelope() -> None:
    module = load_module()

    event = module.create_event(random.Random(1), anomaly_percent=100)

    assert event["event_type"] == "telemetry.received"
    assert event["event_version"] == 1
    assert event["producer"] == "kafka-load-producer"
    assert event["payload"]["status"] in {"warning", "critical"}
    assert event["payload"]["measured_value"] >= event["payload"]["threshold"]


def test_load_producer_writes_one_json_line_per_event() -> None:
    module = load_module()
    stream = io.BytesIO()

    module.write_batch(stream, 25, random.Random(2), anomaly_percent=0)
    lines = stream.getvalue().decode("utf-8").splitlines()

    assert len(lines) == 25
    assert all(json.loads(line)["payload"]["status"] == "normal" for line in lines)
