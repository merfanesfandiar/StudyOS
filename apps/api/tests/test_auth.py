import pytest
from app.core.config import get_settings
from httpx import AsyncClient

from tests.conftest import register_user


@pytest.mark.asyncio
async def test_register_login_and_me(client: AsyncClient) -> None:
    registered = await register_user(client)
    assert registered["user"]["email"] == "student@example.com"
    assert "password_hash" not in registered["user"]

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "STUDENT@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "student@example.com"


@pytest.mark.asyncio
async def test_duplicate_registration_and_invalid_credentials(client: AsyncClient) -> None:
    await register_user(client)
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Another Student",
            "email": "student@example.com",
            "password": "StrongPass123",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    invalid = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "WrongPass123"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_private_endpoint_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/courses")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_auth_endpoints_are_rate_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_max", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 60.0)

    first = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "WrongPass123"},
    )
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "WrongPass123"},
    )
    assert first.status_code == 401, "a wrong password still fails before the throttle matters"
    assert second.status_code == 401

    third = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "WrongPass123"},
    )
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"
    assert third.headers.get("retry-after"), "the client must be told when to retry"


@pytest.mark.asyncio
async def test_a_text_password_is_never_echoed_by_validation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected registration must not echo the password back to anyone."""
    from app.core.config import get_settings as settings_fn

    settings = settings_fn()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_max", 10)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 60.0)

    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "T", "email": "not-an-email", "password": "Sup3rSecret!"},
    )
    assert response.status_code == 422
    body = response.text
    assert "Sup3rSecret!" not in body, "a validation error must not echo the password"
