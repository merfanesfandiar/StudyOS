import pytest
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
