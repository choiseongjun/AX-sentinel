from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient
from pydantic import BaseModel

from shared.config import get_settings


class Role(StrEnum):
    OPERATOR_MANAGER = "operator_manager"
    FIELD_WORKER = "field_worker"
    SYSTEM_ADMIN = "system_admin"


class Principal(BaseModel):
    subject: str
    username: str
    roles: frozenset[Role]


class CognitoTokenVerifier:
    def __init__(self, *, region: str, user_pool_id: str, client_id: str) -> None:
        self._client_id = client_id
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._jwks_client = PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )

    def verify(self, token: str) -> Principal:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self._issuer,
            options={"verify_aud": False},
        )
        if claims.get("token_use") != "access":
            raise jwt.InvalidTokenError("Only Cognito access tokens are accepted")
        if claims.get("client_id") != self._client_id:
            raise jwt.InvalidTokenError("Token was issued for a different client")
        return principal_from_claims(claims)


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    known_roles = {role.value: role for role in Role}
    roles = frozenset(
        known_roles[group]
        for group in claims.get("cognito:groups", [])
        if group in known_roles
    )
    return Principal(
        subject=str(claims["sub"]),
        username=str(claims.get("username", claims["sub"])),
        roles=roles,
    )


@lru_cache
def get_token_verifier() -> CognitoTokenVerifier:
    settings = get_settings()
    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        raise RuntimeError("Cognito authentication settings are incomplete")
    return CognitoTokenVerifier(
        region=settings.aws_region,
        user_pool_id=settings.cognito_user_pool_id,
        client_id=settings.cognito_client_id,
    )


def local_principal() -> Principal:
    return Principal(
        subject="local-development-user",
        username="local-admin",
        roles=frozenset(Role),
    )


def require_roles(*allowed_roles: Role):
    async def dependency(request: Request) -> Principal:
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not principal.roles.intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return principal

    return dependency
