from fastapi.testclient import TestClient

from shared.api import create_app
from shared.auth import Role, principal_from_claims
from shared.config import get_settings


def test_cognito_groups_map_to_known_roles() -> None:
    principal = principal_from_claims(
        {
            "sub": "user-123",
            "username": "operator@example.com",
            "cognito:groups": ["operator_manager", "unknown_group"],
        }
    )

    assert principal.subject == "user-123"
    assert principal.roles == frozenset({Role.OPERATOR_MANAGER})


def test_user_without_groups_has_no_roles() -> None:
    principal = principal_from_claims({"sub": "user-456"})

    assert principal.roles == frozenset()


def test_cognito_mode_requires_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "cognito")
    get_settings.cache_clear()
    app = create_app("auth-test")

    @app.get("/private")
    async def private_route() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.get("/private").status_code == 401
    get_settings.cache_clear()
