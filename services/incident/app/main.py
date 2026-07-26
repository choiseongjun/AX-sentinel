from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.dynamodb import get_repository

app = create_app("incident-service")


class IncidentStatus(StrEnum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class VirtualIncidentRequest(BaseModel):
    equipment_id: str
    sensor_type: str
    measured_value: float
    threshold: float
    error_code: str
    log_excerpt: str = Field(max_length=2000)


class Incident(BaseModel):
    id: str
    equipment_id: str
    status: IncidentStatus
    severity: str
    detected_at: datetime
    payload: VirtualIncidentRequest


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class TelemetryRequest(BaseModel):
    equipment_id: str
    sensor_type: str
    measured_value: float
    unit: str = ""
    threshold: float
    log_excerpt: str = Field(default="", max_length=2000)


class TelemetryRecord(TelemetryRequest):
    id: str
    status: str
    received_at: datetime


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {IncidentStatus.ANALYZING},
    IncidentStatus.ANALYZING: {
        IncidentStatus.REVIEW_REQUIRED,
        IncidentStatus.APPROVED,
    },
    IncidentStatus.REVIEW_REQUIRED: {IncidentStatus.APPROVED},
    IncidentStatus.APPROVED: {IncidentStatus.IN_PROGRESS},
    IncidentStatus.IN_PROGRESS: {IncidentStatus.RESOLVED},
    IncidentStatus.RESOLVED: set(),
}


@app.post(
    "/api/v1/telemetry",
    response_model=TelemetryRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["telemetry"],
)
async def ingest_telemetry(
    request: TelemetryRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> TelemetryRecord:
    ratio = request.measured_value / request.threshold if request.threshold else 0
    telemetry = TelemetryRecord(
        **request.model_dump(),
        id=str(uuid4()),
        status="critical" if ratio >= 1.2 else "warning" if ratio >= 1 else "normal",
        received_at=datetime.now(UTC),
    )
    await run_in_threadpool(
        get_repository().put,
        "telemetry",
        telemetry.id,
        telemetry,
    )
    return telemetry


@app.get("/api/v1/telemetry", response_model=list[TelemetryRecord], tags=["telemetry"])
async def list_telemetry(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TelemetryRecord]:
    values = await run_in_threadpool(get_repository().list, "telemetry")
    records = [TelemetryRecord.model_validate(value) for value in values]
    return sorted(records, key=lambda item: item.received_at, reverse=True)[:limit]


@app.post(
    "/api/v1/incidents/simulate",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
    tags=["incidents"],
)
async def simulate_incident(
    request: VirtualIncidentRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> Incident:
    incident = Incident(
        id=str(uuid4()),
        equipment_id=request.equipment_id,
        status=IncidentStatus.DETECTED,
        severity="critical" if request.measured_value >= request.threshold * 1.2 else "high",
        detected_at=datetime.now(UTC),
        payload=request,
    )
    repository = get_repository()
    await run_in_threadpool(repository.put, "incident", incident.id, incident)
    return incident


@app.get("/api/v1/incidents", response_model=list[Incident], tags=["incidents"])
async def list_incidents() -> list[Incident]:
    values = await run_in_threadpool(get_repository().list, "incident")
    incidents = [Incident.model_validate(value) for value in values]
    return sorted(incidents, key=lambda item: item.detected_at, reverse=True)


@app.get("/api/v1/incidents/{incident_id}", response_model=Incident, tags=["incidents"])
async def get_incident(incident_id: str) -> Incident:
    value = await run_in_threadpool(get_repository().get, "incident", incident_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return Incident.model_validate(value)


@app.patch(
    "/api/v1/incidents/{incident_id}/status",
    response_model=Incident,
    tags=["incidents"],
)
async def update_incident_status(
    incident_id: str,
    update: IncidentStatusUpdate,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.FIELD_WORKER, Role.SYSTEM_ADMIN)),
    ],
) -> Incident:
    value = await run_in_threadpool(get_repository().get, "incident", incident_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident = Incident.model_validate(value)
    if update.status not in ALLOWED_TRANSITIONS[incident.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid transition: {incident.status} -> {update.status}",
        )
    incident.status = update.status
    await run_in_threadpool(get_repository().put, "incident", incident.id, incident)
    return incident
