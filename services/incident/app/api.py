from typing import Annotated

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from shared.auth import Principal, Role, get_token_verifier, require_roles
from shared.concurrency import run_authentication

from .application import (
    IncidentApplicationService,
    IncidentNotFoundError,
    InvalidIncidentTransitionError,
)
from .models import (
    Incident,
    IncidentStatusUpdate,
    TelemetryRecord,
    TelemetryRequest,
    VirtualIncidentRequest,
)
from .realtime import RealtimeHub


def create_incident_router(
    service: IncidentApplicationService,
    realtime: RealtimeHub,
    *,
    auth_mode: str,
) -> APIRouter:
    router = APIRouter()

    def websocket_access_token(
        websocket: WebSocket,
    ) -> tuple[str | None, str | None]:
        protocols = [
            value.strip()
            for value in websocket.headers.get(
                "sec-websocket-protocol",
                "",
            ).split(",")
            if value.strip()
        ]
        if len(protocols) >= 2 and protocols[0] == "access-token":
            return protocols[1], "access-token"
        return None, None

    async def authorize_websocket(websocket: WebSocket) -> str | None:
        if auth_mode == "disabled":
            return None

        token, subprotocol = websocket_access_token(websocket)
        if token is None:
            await websocket.close(code=4401, reason="Access token required")
            return None

        try:
            await run_authentication(get_token_verifier().verify, token)
        except (jwt.PyJWTError, RuntimeError):
            await websocket.close(
                code=4401,
                reason="Invalid or expired access token",
            )
            return None
        return subprotocol

    @router.post(
        "/api/v1/telemetry",
        response_model=TelemetryRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["telemetry"],
    )
    async def ingest_telemetry(
        request: TelemetryRequest,
        principal: Annotated[
            Principal,
            Depends(
                require_roles(
                    Role.OPERATOR_MANAGER,
                    Role.SYSTEM_ADMIN,
                )
            ),
        ],
    ) -> TelemetryRecord:
        return await service.ingest_telemetry(
            request,
            actor_id=principal.subject,
        )

    @router.get(
        "/api/v1/telemetry",
        response_model=list[TelemetryRecord],
        tags=["telemetry"],
    )
    async def list_telemetry(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[TelemetryRecord]:
        return await service.list_telemetry(limit=limit)

    @router.websocket("/api/v1/telemetry/ws")
    async def telemetry_websocket(websocket: WebSocket) -> None:
        subprotocol = await authorize_websocket(websocket)
        if auth_mode != "disabled" and subprotocol is None:
            return

        await realtime.telemetry.connect(websocket, subprotocol)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            realtime.telemetry.disconnect(websocket)

    @router.websocket("/api/v1/incidents/ws")
    async def incident_websocket(websocket: WebSocket) -> None:
        subprotocol = await authorize_websocket(websocket)
        if auth_mode != "disabled" and subprotocol is None:
            return

        await realtime.incidents.connect(websocket, subprotocol)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            realtime.incidents.disconnect(websocket)

    @router.post(
        "/api/v1/incidents/simulate",
        response_model=Incident,
        status_code=status.HTTP_201_CREATED,
        tags=["incidents"],
    )
    async def simulate_incident(
        request: VirtualIncidentRequest,
        principal: Annotated[
            Principal,
            Depends(
                require_roles(
                    Role.OPERATOR_MANAGER,
                    Role.SYSTEM_ADMIN,
                )
            ),
        ],
    ) -> Incident:
        return await service.simulate_incident(
            request,
            actor_id=principal.subject,
        )

    @router.get(
        "/api/v1/incidents",
        response_model=list[Incident],
        tags=["incidents"],
    )
    async def list_incidents() -> list[Incident]:
        return await service.list_incidents()

    @router.get(
        "/api/v1/incidents/{incident_id}",
        response_model=Incident,
        tags=["incidents"],
    )
    async def get_incident(incident_id: str) -> Incident:
        try:
            return await service.get_incident(incident_id)
        except IncidentNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Incident not found",
            ) from exc

    @router.patch(
        "/api/v1/incidents/{incident_id}/status",
        response_model=Incident,
        tags=["incidents"],
    )
    async def update_incident_status(
        incident_id: str,
        update: IncidentStatusUpdate,
        principal: Annotated[
            Principal,
            Depends(
                require_roles(
                    Role.OPERATOR_MANAGER,
                    Role.FIELD_WORKER,
                    Role.SYSTEM_ADMIN,
                )
            ),
        ],
    ) -> Incident:
        try:
            return await service.update_incident_status(
                incident_id,
                update.status,
                actor_id=principal.subject,
            )
        except IncidentNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Incident not found",
            ) from exc
        except InvalidIncidentTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
