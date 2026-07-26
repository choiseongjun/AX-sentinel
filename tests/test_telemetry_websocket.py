import asyncio
from datetime import UTC, datetime
from typing import Any

from services.incident.app.main import TelemetryRecord, WebSocketConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted_subprotocol: str | None = None
        self.messages: list[dict[str, Any]] = []

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_telemetry_connection_broadcasts_json_record() -> None:
    async def scenario() -> None:
        manager = WebSocketConnectionManager()
        socket: Any = FakeWebSocket()
        record = TelemetryRecord(
            id="sample-1",
            equipment_id="PRESS-001",
            sensor_type="bearing_temperature",
            measured_value=96.4,
            unit="C",
            threshold=90,
            status="warning",
            received_at=datetime.now(UTC),
            log_excerpt="bearing_temperature threshold exceeded",
        )

        await manager.connect(socket)
        await manager.broadcast(record)

        assert socket.messages[0]["id"] == "sample-1"
        assert socket.messages[0]["status"] == "warning"
        manager.disconnect(socket)

    asyncio.run(scenario())
