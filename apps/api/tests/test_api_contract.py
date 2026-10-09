"""The public API contract that the audit flagged as undocumented.

Two guarantees live here and nowhere else:

- Every HTTP error body is emitted by the single ``ErrorResponse`` schema, so a
  generated client that understands the schema can parse any documented error
  status. We prove one real body against the model and that the OpenAPI schema
  advertises it.
- The interactive docs are development tooling. They exist in any
  non-production environment and are hard-gated off in production regardless of
  ``docs_enabled``.
"""

import importlib

import pytest
from app.core.config import get_settings
from app.schemas.common import ErrorResponse
from httpx import ASGITransport, AsyncClient

from tests.conftest import register_user


@pytest.mark.asyncio
async def test_interactive_docs_are_served_in_development(client: AsyncClient) -> None:
    assert (await client.get("/openapi.json")).status_code == 200
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/redoc")).status_code == 200


@pytest.mark.asyncio
async def test_interactive_docs_are_hard_gated_off_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "s" * 32)
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    reloaded = importlib.reload(main_module)
    transport = ASGITransport(app=reloaded.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as production:
        assert (await production.get("/openapi.json")).status_code == 404
        assert (await production.get("/docs")).status_code == 404
        assert (await production.get("/redoc")).status_code == 404
        assert "docs" not in (await production.get("/")).json()

    # Put the development app back for the rest of the suite.
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    importlib.reload(main_module)


@pytest.mark.asyncio
async def test_openapi_documents_the_error_response_schema(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "ErrorResponse" in schema["components"]["schemas"]

    login = schema["paths"]["/api/v1/auth/login"]["post"]
    for status in ("401", "422", "429"):
        ref = login["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/components/schemas/ErrorResponse"), ref


@pytest.mark.asyncio
async def test_error_bodies_match_the_shared_schema(client: AsyncClient) -> None:
    await register_user(client)
    missing = await client.get("/api/v1/courses/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    body = missing.json()
    ErrorResponse.model_validate(body)
    assert body["error"]["code"] == "COURSE_NOT_FOUND"


@pytest.mark.asyncio
async def test_validation_error_bodies_match_the_shared_schema(client: AsyncClient) -> None:
    await register_user(client)
    invalid = await client.post(
        "/api/v1/auth/register",
        json={"name": "", "email": "not-an-email", "password": "short"},
    )
    assert invalid.status_code == 422
    ErrorResponse.model_validate(invalid.json())