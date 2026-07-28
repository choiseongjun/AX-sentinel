import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from services.incident.app.application import (
    INCIDENT_CHANNEL,
    TELEMETRY_CHANNEL,
    IncidentApplicationService,
    InvalidIncidentTransitionError,
)
from services.incident.app.models import (
    IncidentStatus,
    TelemetryRequest,
    VirtualIncidentRequest,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict[str, Any]] = {}

    async def put(
        self,
        entity_type: str,
        entity_id: str,
        value: BaseModel | dict[str, Any],
    ) -> None:
        self.values[(entity_type, entity_id)] = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )

    async def get(
        self,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        return self.values.get((entity_type, entity_id))

    async def list(self, entity_type: str) -> list[dict[str, Any]]:
        return [
            value
            for (stored_type, _), value in self.values.items()
            if stored_type == entity_type
        ]


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        **metadata: Any,
    ) -> None:
        self.items.append((event_type, payload, metadata))


class RecordingRealtime:
    def __init__(self) -> None:
        self.items: list[tuple[str, BaseModel]] = []

    async def publish(self, channel: str, model: BaseModel) -> None:
        self.items.append((channel, model))


def create_service(
    ids: list[str],
) -> tuple[IncidentApplicationService, MemoryRepository, RecordingEvents, RecordingRealtime]:
    repository = MemoryRepository()
    events = RecordingEvents()
    realtime = RecordingRealtime()
    id_values = iter(ids)
    service = IncidentApplicationService(
        repository=repository,
        events=events,
        realtime=realtime,
        id_factory=lambda: next(id_values),
        clock=lambda: datetime(2026, 7, 28, tzinfo=UTC),
    )
    return service, repository, events, realtime


def test_ingest_telemetry_coordinates_storage_event_and_realtime() -> None:
    service, repository, events, realtime = create_service(["telemetry-1"])

    telemetry = asyncio.run(
        service.ingest_telemetry(
            TelemetryRequest(
                equipment_id="PRESS-001",
                sensor_type="bearing_temperature",
                measured_value=72,
                unit="C",
                threshold=90,
            ),
            actor_id="manager-1",
        )
    )

    assert telemetry.id == "telemetry-1"
    assert telemetry.status == "normal"
    assert ("telemetry", "telemetry-1") in repository.values
    assert events.items[0][0] == "telemetry.received"
    assert events.items[0][2]["actor_id"] == "manager-1"
    assert realtime.items[0][0] == TELEMETRY_CHANNEL


def test_critical_telemetry_creates_one_automatic_incident() -> None:
    service, repository, events, realtime = create_service(
        ["telemetry-1", "incident-1", "telemetry-2"]
    )
    request = TelemetryRequest(
        equipment_id="PRESS-001",
        sensor_type="bearing_temperature",
        measured_value=112,
        unit="C",
        threshold=90,
    )

    asyncio.run(service.ingest_telemetry(request, actor_id="manager-1"))
    asyncio.run(service.ingest_telemetry(request, actor_id="manager-1"))

    incidents = asyncio.run(service.list_incidents())
    assert len(incidents) == 1
    assert incidents[0].source == "automatic"
    assert incidents[0].severity == "critical"
    assert [item[0] for item in events.items].count("incident.detected") == 1
    detected_event = next(item for item in events.items if item[0] == "incident.detected")
    assert detected_event[2]["key"] is None
    assert [channel for channel, _ in realtime.items].count(INCIDENT_CHANNEL) == 1
    assert ("incident", "incident-1") in repository.values


def test_status_transition_policy_is_enforced_by_application_service() -> None:
    service, _, events, _ = create_service(["incident-1"])
    request = VirtualIncidentRequest(
        equipment_id="PRESS-001",
        sensor_type="vibration_rms",
        measured_value=12,
        threshold=10,
        error_code="E-VIB-001",
        log_excerpt="threshold exceeded",
    )
    incident = asyncio.run(
        service.simulate_incident(request, actor_id="manager-1")
    )
    assert events.items[-1][2]["key"] == "incident-1"

    analyzing = asyncio.run(
        service.update_incident_status(
            incident.id,
            IncidentStatus.ANALYZING,
            actor_id="manager-1",
        )
    )
    assert analyzing.status == IncidentStatus.ANALYZING
    assert events.items[-1][0] == "incident.status_changed"

    with pytest.raises(InvalidIncidentTransitionError):
        asyncio.run(
            service.update_incident_status(
                incident.id,
                IncidentStatus.RESOLVED,
                actor_id="manager-1",
            )
        )
