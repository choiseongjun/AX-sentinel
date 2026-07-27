import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, get_token_verifier, require_roles
from shared.config import get_settings
from shared.dynamodb import get_repository
from shared.events import get_event_publisher
from shared.realtime import get_realtime_bus

from .detection import AnomalyDetector, DetectionSignal


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


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, subprotocol: str | None = None) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, model: BaseModel | dict[str, object]) -> None:
        message = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
        disconnected: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json(message)
            except (OSError, RuntimeError, WebSocketDisconnect):
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)


telemetry_connections = WebSocketConnectionManager()
incident_connections = WebSocketConnectionManager()
anomaly_detector = AnomalyDetector()
realtime_listener_task: asyncio.Task[None] | None = None


async def _publish_realtime(
    channel: str,
    manager: WebSocketConnectionManager,
    model: BaseModel,
) -> None:
    if get_settings().websocket_broker == "redis":
        await get_realtime_bus().publish(channel, model.model_dump(mode="json"))
    else:
        await manager.broadcast(model)


async def _start_realtime_listener() -> None:
    global realtime_listener_task
    if get_settings().websocket_broker != "redis":
        return

    ready = asyncio.Event()
    realtime_listener_task = asyncio.create_task(
        get_realtime_bus().listen(
            {
                "ax-sentinel.telemetry": telemetry_connections.broadcast,
                "ax-sentinel.incidents": incident_connections.broadcast,
            },
            ready,
        )
    )
    await asyncio.wait_for(ready.wait(), timeout=10)


async def _stop_realtime_listener() -> None:
    global realtime_listener_task
    if realtime_listener_task is not None:
        realtime_listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await realtime_listener_task
        realtime_listener_task = None
    if get_settings().websocket_broker == "redis":
        await get_realtime_bus().close()


app = create_app(
    "incident-service",
    startup=_start_realtime_listener,
    shutdown=_stop_realtime_listener,
)


def _websocket_access_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    if len(protocols) >= 2 and protocols[0] == "access-token":
        return protocols[1], "access-token"
    return None, None


async def _authorize_websocket(websocket: WebSocket) -> str | None:
    if get_settings().auth_mode == "disabled":
        return None

    token, subprotocol = _websocket_access_token(websocket)
    if token is None:
        await websocket.close(code=4401, reason="Access token required")
        return None

    try:
        await run_in_threadpool(get_token_verifier().verify, token)
    except (jwt.PyJWTError, RuntimeError):
        await websocket.close(code=4401, reason="Invalid or expired access token")
        return None
    return subprotocol


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


async def _create_automatic_incident(telemetry: TelemetryRecord) -> Incident | None:
    trigger_code = anomaly_detector.evaluate(
        DetectionSignal(
            equipment_id=telemetry.equipment_id,
            sensor_type=telemetry.sensor_type,
            status=telemetry.status,
        )
    )
    if trigger_code is None:
        return None

    repository = get_repository()
    existing_values = await run_in_threadpool(repository.list, "incident")
    existing_incidents = [Incident.model_validate(value) for value in existing_values]
    duplicate_exists = any(
        incident.status != IncidentStatus.RESOLVED
        and incident.equipment_id == telemetry.equipment_id
        and incident.payload.sensor_type == telemetry.sensor_type
        for incident in existing_incidents
    )
    if duplicate_exists:
        return None

    incident = Incident(
        id=str(uuid4()),
        equipment_id=telemetry.equipment_id,
        status=IncidentStatus.DETECTED,
        severity="critical" if telemetry.status == "critical" else "high",
        detected_at=datetime.now(UTC),
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
    await run_in_threadpool(repository.put, "incident", incident.id, incident)
    await run_in_threadpool(
        get_event_publisher().publish,
        "incident.detected",
        incident.model_dump(mode="json"),
        alert=True,
    )
    await _publish_realtime("ax-sentinel.incidents", incident_connections, incident)
    return incident


@app.post(
    "/api/v1/telemetry",
    response_model=TelemetryRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["telemetry"],
)
async def ingest_telemetry(
    request: TelemetryRequest,
    principal: Annotated[
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
    await run_in_threadpool(
        get_event_publisher().publish,
        "telemetry.received",
        telemetry.model_dump(mode="json"),
        key=telemetry.equipment_id,
        actor_id=principal.subject,
    )
    await _publish_realtime("ax-sentinel.telemetry", telemetry_connections, telemetry)
    await _create_automatic_incident(telemetry)
    return telemetry


@app.get("/api/v1/telemetry", response_model=list[TelemetryRecord], tags=["telemetry"])
async def list_telemetry(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TelemetryRecord]:
    values = await run_in_threadpool(get_repository().list, "telemetry")
    records = [TelemetryRecord.model_validate(value) for value in values]
    return sorted(records, key=lambda item: item.received_at, reverse=True)[:limit]


@app.websocket("/api/v1/telemetry/ws")
async def telemetry_websocket(websocket: WebSocket) -> None:
    subprotocol = await _authorize_websocket(websocket)
    if get_settings().auth_mode != "disabled" and subprotocol is None:
        return

    await telemetry_connections.connect(websocket, subprotocol)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        telemetry_connections.disconnect(websocket)


@app.websocket("/api/v1/incidents/ws")
async def incident_websocket(websocket: WebSocket) -> None:
    subprotocol = await _authorize_websocket(websocket)
    if get_settings().auth_mode != "disabled" and subprotocol is None:
        return

    await incident_connections.connect(websocket, subprotocol)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        incident_connections.disconnect(websocket)


@app.post(
    "/api/v1/incidents/simulate",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
    tags=["incidents"],
)
async def simulate_incident(
    request: VirtualIncidentRequest,
    principal: Annotated[
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
    await run_in_threadpool(
        get_event_publisher().publish,
        "incident.detected",
        incident.model_dump(mode="json"),
        key=incident.id,
        actor_id=principal.subject,
        alert=True,
    )
    await _publish_realtime("ax-sentinel.incidents", incident_connections, incident)
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
    principal: Annotated[
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
    previous_status = incident.status
    incident.status = update.status
    await run_in_threadpool(get_repository().put, "incident", incident.id, incident)
    await run_in_threadpool(
        get_event_publisher().publish,
        "incident.status_changed",
        {
            "id": incident.id,
            "incident_id": incident.id,
            "equipment_id": incident.equipment_id,
            "previous_status": previous_status,
            "status": incident.status,
        },
        key=incident.id,
        actor_id=principal.subject,
    )
    await _publish_realtime("ax-sentinel.incidents", incident_connections, incident)
    return incident
