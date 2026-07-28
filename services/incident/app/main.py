from shared.api import create_app
from shared.config import get_settings
from shared.dynamodb import get_repository
from shared.events import get_event_publisher
from shared.realtime import get_realtime_bus

from .adapters import AsyncDomainEventPublisher, AsyncDynamoRepository
from .api import create_incident_router
from .application import IncidentApplicationService
from .models import (
    Incident,
    IncidentStatusUpdate,
    TelemetryRecord,
    TelemetryRequest,
    VirtualIncidentRequest,
)
from .realtime import RealtimeHub, WebSocketConnectionManager

__all__ = [
    "Incident",
    "IncidentStatusUpdate",
    "TelemetryRecord",
    "TelemetryRequest",
    "VirtualIncidentRequest",
    "WebSocketConnectionManager",
    "app",
]

settings = get_settings()
realtime_hub = RealtimeHub(
    broker=settings.websocket_broker,
    redis_bus=get_realtime_bus() if settings.websocket_broker == "redis" else None,
)
incident_service = IncidentApplicationService(
    repository=AsyncDynamoRepository(get_repository()),
    events=AsyncDomainEventPublisher(get_event_publisher()),
    realtime=realtime_hub,
)

app = create_app(
    "incident-service",
    startup=realtime_hub.start,
    shutdown=realtime_hub.stop,
)
app.include_router(
    create_incident_router(
        incident_service,
        realtime_hub,
        auth_mode=settings.auth_mode,
    )
)
