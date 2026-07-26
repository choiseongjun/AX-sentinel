from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.auth import get_token_verifier, local_principal
from shared.config import get_settings


class HealthResponse(BaseModel):
    service: str
    status: str
    timestamp: datetime


def create_app(service_name: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title=f"AX Sentinel {service_name}",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        public_path = (
            request.url.path.startswith("/health/")
            or request.url.path in {"/docs", "/redoc", "/openapi.json"}
        )
        if public_path:
            return await call_next(request)

        settings = get_settings()
        if settings.auth_mode == "disabled":
            request.state.principal = local_principal()
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer access token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            request.state.principal = await run_in_threadpool(
                get_token_verifier().verify,
                token,
            )
        except (jwt.PyJWTError, RuntimeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired access token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)

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
