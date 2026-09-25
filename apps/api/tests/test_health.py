import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_and_readiness(client: AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
