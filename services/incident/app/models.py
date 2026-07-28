from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
    source: str = "manual"
    telemetry_id: str | None = None


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


ALLOWED_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.DETECTED: frozenset({IncidentStatus.ANALYZING}),
    IncidentStatus.ANALYZING: frozenset(
        {
            IncidentStatus.REVIEW_REQUIRED,
            IncidentStatus.APPROVED,
        }
    ),
    IncidentStatus.REVIEW_REQUIRED: frozenset({IncidentStatus.APPROVED}),
    IncidentStatus.APPROVED: frozenset({IncidentStatus.IN_PROGRESS}),
    IncidentStatus.IN_PROGRESS: frozenset({IncidentStatus.RESOLVED}),
    IncidentStatus.RESOLVED: frozenset(),
}


def telemetry_status(measured_value: float, threshold: float) -> str:
    ratio = measured_value / threshold if threshold else 0
    return "critical" if ratio >= 1.2 else "warning" if ratio >= 1 else "normal"


def incident_severity(measured_value: float, threshold: float) -> str:
    return "critical" if measured_value >= threshold * 1.2 else "high"
