import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    """
    Base test: health endpoint working
    If this test fails, the entire app is not working
    """
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "checks" in data
    assert data["checks"]["postgres"] == "ok"


@pytest.mark.asyncio
async def test_health_contains_version(client: AsyncClient):
    response = await client.get("/health")
    data = response.json()
    assert "version" in data
    assert data["version"] == "0.1.0"
