from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from .detection import AnomalyDetector, DetectionSignal
from .models import (
    ALLOWED_TRANSITIONS,
    Incident,
    IncidentStatus,
    TelemetryRecord,
    TelemetryRequest,
    VirtualIncidentRequest,
    incident_severity,
    telemetry_status,
)
from .ports import DomainEventPublisher, EntityRepository, RealtimePublisher

TELEMETRY_CHANNEL = "ax-sentinel.telemetry"
INCIDENT_CHANNEL = "ax-sentinel.incidents"


class IncidentNotFoundError(LookupError):
    pass


class InvalidIncidentTransitionError(ValueError):
    def __init__(
        self,
        current: IncidentStatus,
        requested: IncidentStatus,
    ) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"Invalid transition: {current} -> {requested}")


class IncidentApplicationService:
    """Orchestrates incident use cases without depending on FastAPI or boto3."""

    def __init__(
        self,
        *,
        repository: EntityRepository,
        events: DomainEventPublisher,
        realtime: RealtimePublisher,
        detector: AnomalyDetector | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._events = events
        self._realtime = realtime
        self._detector = detector or AnomalyDetector()
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    async def ingest_telemetry(
        self,
        request: TelemetryRequest,
        *,
        actor_id: str,
    ) -> TelemetryRecord:
        telemetry = TelemetryRecord(
            **request.model_dump(),
            id=self._id_factory(),
            status=telemetry_status(request.measured_value, request.threshold),
            received_at=self._clock(),
        )
        await self._repository.put("telemetry", telemetry.id, telemetry)
        await self._events.publish(
            "telemetry.received",
            telemetry.model_dump(mode="json"),
            key=telemetry.equipment_id,
            actor_id=actor_id,
        )
        await self._realtime.publish(TELEMETRY_CHANNEL, telemetry)
        await self._create_automatic_incident(telemetry)
        return telemetry

    async def _create_automatic_incident(
        self,
        telemetry: TelemetryRecord,
    ) -> Incident | None:
        trigger_code = self._detector.evaluate(
            DetectionSignal(
                equipment_id=telemetry.equipment_id,
                sensor_type=telemetry.sensor_type,
                status=telemetry.status,
            )
        )
        if trigger_code is None:
            return None

        existing_incidents = await self.list_incidents()
        duplicate_exists = any(
            incident.status != IncidentStatus.RESOLVED
            and incident.equipment_id == telemetry.equipment_id
            and incident.payload.sensor_type == telemetry.sensor_type
            for incident in existing_incidents
        )
        if duplicate_exists:
            return None

        incident = Incident(
            id=self._id_factory(),
            equipment_id=telemetry.equipment_id,
            status=IncidentStatus.DETECTED,
            severity=incident_severity(
                telemetry.measured_value,
                telemetry.threshold,
            ),
            detected_at=self._clock(),
            payload=VirtualIncidentRequest(
                equipment_id=telemetry.equipment_id,
                sensor_type=telemetry.sensor_type,
                measured_value=telemetry.measured_value,
                threshold=telemetry.threshold,
                error_code=trigger_code,
                log_excerpt=telemetry.log_excerpt,
            ),
            source="automatic",
            telemetry_id=telemetry.id,
        )
        await self._save_detected_incident(
            incident,
            actor_id=None,
            event_key=None,
        )
        return incident

    async def simulate_incident(
        self,
        request: VirtualIncidentRequest,
        *,
        actor_id: str,
    ) -> Incident:
        incident = Incident(
            id=self._id_factory(),
            equipment_id=request.equipment_id,
            status=IncidentStatus.DETECTED,
            severity=incident_severity(
                request.measured_value,
                request.threshold,
            ),
            detected_at=self._clock(),
            payload=request,
        )
        await self._save_detected_incident(
            incident,
            actor_id=actor_id,
            event_key=incident.id,
        )
        return incident

    async def _save_detected_incident(
        self,
        incident: Incident,
        *,
        actor_id: str | None,
        event_key: str | None,
    ) -> None:
        await self._repository.put("incident", incident.id, incident)
        await self._events.publish(
            "incident.detected",
            incident.model_dump(mode="json"),
            key=event_key,
            actor_id=actor_id,
            alert=True,
        )
        await self._realtime.publish(INCIDENT_CHANNEL, incident)

    async def list_telemetry(self, *, limit: int = 100) -> list[TelemetryRecord]:
        values = await self._repository.list("telemetry")
        records = [TelemetryRecord.model_validate(value) for value in values]
        return sorted(records, key=lambda item: item.received_at, reverse=True)[:limit]

    async def list_incidents(self) -> list[Incident]:
        values = await self._repository.list("incident")
        incidents = [Incident.model_validate(value) for value in values]
        return sorted(incidents, key=lambda item: item.detected_at, reverse=True)

    async def get_incident(self, incident_id: str) -> Incident:
        value = await self._repository.get("incident", incident_id)
        if value is None:
            raise IncidentNotFoundError(incident_id)
        return Incident.model_validate(value)

    async def update_incident_status(
        self,
        incident_id: str,
        requested_status: IncidentStatus,
        *,
        actor_id: str,
    ) -> Incident:
        incident = await self.get_incident(incident_id)
        if requested_status not in ALLOWED_TRANSITIONS[incident.status]:
            raise InvalidIncidentTransitionError(
                incident.status,
                requested_status,
            )

        previous_status = incident.status
        incident.status = requested_status
        await self._repository.put("incident", incident.id, incident)
        await self._events.publish(
            "incident.status_changed",
            {
                "id": incident.id,
                "incident_id": incident.id,
                "equipment_id": incident.equipment_id,
                "previous_status": previous_status,
                "status": incident.status,
            },
            key=incident.id,
            actor_id=actor_id,
        )
        await self._realtime.publish(INCIDENT_CHANNEL, incident)
        return incident
