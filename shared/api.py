from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import perf_counter

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from shared.auth import get_token_verifier, local_principal
from shared.concurrency import run_authentication, shutdown_blocking_executors
from shared.config import get_settings

HTTP_REQUESTS = Counter(
    "ax_sentinel_http_requests_total",
    "HTTP requests handled by AX Sentinel services",
    ["service", "method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "ax_sentinel_http_request_duration_seconds",
    "HTTP request latency for AX Sentinel services",
    ["service", "method", "path"],
)


class HealthResponse(BaseModel):
    service: str
    status: str
    timestamp: datetime


def create_app(
    service_name: str,
    *,
    startup: Callable[[], Awaitable[None]] | None = None,
    shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if startup is not None:
            await startup()
        try:
            yield
        finally:
            if shutdown is not None:
                await shutdown()
            shutdown_blocking_executors()

    app = FastAPI(
        title=f"AX Sentinel {service_name}",
        version="0.1.0",
        lifespan=lifespan,
    )
    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        started_at = perf_counter()
        public_path = (
            request.url.path.startswith("/health/")
            or request.url.path.startswith("/metrics")
            or request.url.path in {"/docs", "/redoc", "/openapi.json"}
        )
        if public_path:
            response = await call_next(request)
            HTTP_REQUESTS.labels(
                service_name, request.method, request.url.path, response.status_code
            ).inc()
            HTTP_DURATION.labels(service_name, request.method, request.url.path).observe(
                perf_counter() - started_at
            )
            return response

        settings = get_settings()
        if settings.auth_mode == "disabled":
            request.state.principal = local_principal()
            response = await call_next(request)
            HTTP_REQUESTS.labels(
                service_name, request.method, request.url.path, response.status_code
            ).inc()
            HTTP_DURATION.labels(service_name, request.method, request.url.path).observe(
                perf_counter() - started_at
            )
            return response

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer access token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            request.state.principal = await run_authentication(
                get_token_verifier().verify,
                token,
            )
        except (jwt.PyJWTError, RuntimeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired access token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        response = await call_next(request)
        HTTP_REQUESTS.labels(
            service_name, request.method, request.url.path, response.status_code
        ).inc()
        HTTP_DURATION.labels(service_name, request.method, request.url.path).observe(
            perf_counter() - started_at
        )
        return response

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health/live", response_model=HealthResponse, tags=["platform"])
    async def liveness() -> HealthResponse:
        return HealthResponse(
            service=service_name,
            status="ok",
            timestamp=datetime.now(UTC),
        )

    @app.get("/health/ready", response_model=HealthResponse, tags=["platform"])
    async def readiness() -> HealthResponse:
        return HealthResponse(
            service=service_name,
            status="ready",
            timestamp=datetime.now(UTC),
        )

    return app
