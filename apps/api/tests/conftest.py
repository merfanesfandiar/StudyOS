import importlib
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import pytest
from app.core.rate_limit import reset_rate_limits
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.storage.local import LocalStorage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

documents_module = importlib.import_module("app.modules.documents.router")
assignments_module = importlib.import_module("app.modules.assignments.router")

# Set by CI to run the suite against a real PostgreSQL, the dialect every
# deployed environment uses. Locally the suite stays on in-memory SQLite.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    if TEST_DATABASE_URL:
        engine = create_async_engine(
            TEST_DATABASE_URL, poolclass=NullPool, pool_pre_ping=True
        )
        # Drop first so a crash in a previous test leaves no residue, then
        # create fresh: every test starts from the same empty schema the
        # SQLite path gives it.
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _enable_sqlite_foreign_keys(engine)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    storage = LocalStorage(tmp_path / "uploads")
    monkeypatch.setattr(documents_module, "get_storage", lambda: storage)
    monkeypatch.setattr(assignments_module, "get_storage", lambda: storage)
    reset_rate_limits()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def register_user(client: AsyncClient, email: str = "student@example.com") -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Test Student", "email": email, "password": "StrongPass123"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())
