from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app


@pytest_asyncio.fixture
async def health_client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    # [ЧТО] Подменяем Postgres и Redis в /health, чтобы unit-тест не требовал docker-сервисы.
    # [ПОЧЕМУ] conftest `client` поднимает реальную test_engine — для health это избыточно.
    # [ОСТОРОЖНО] Не забывать снимать dependency_overrides, иначе следующие тесты увидят мок.
    async def _override_get_db() -> object:
        session = MagicMock()
        session.execute = AsyncMock()
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()
    monkeypatch.setattr(
        "app.api.routers.health.aioredis.from_url",
        lambda *_a: mock_redis,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_returns_ok(health_client: AsyncClient) -> None:
    response = await health_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "checks" in data
    assert data["checks"]["postgres"] == "ok"
    assert data["checks"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_contains_version(health_client: AsyncClient) -> None:
    response = await health_client.get("/health")
    data = response.json()
    assert "version" in data
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_postgres_error_marks_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _bad_db() -> object:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("db down"))
        yield session

    app.dependency_overrides[get_db] = _bad_db

    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()
    monkeypatch.setattr(
        "app.api.routers.health.aioredis.from_url",
        lambda *_a: mock_redis,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        response = await ac.get("/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "error" in data["checks"]["postgres"]
