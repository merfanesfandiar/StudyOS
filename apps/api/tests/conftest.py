import importlib
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.storage.local import LocalStorage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

documents_module = importlib.import_module("app.modules.documents.router")
assignments_module = importlib.import_module("app.modules.assignments.router")


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def register_user(client: AsyncClient, email: str = "student@example.com") -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Test Student", "email": email, "password": "StrongPass123"},
    )
    assert response.status_code == 201, response.text
    return response.json()
