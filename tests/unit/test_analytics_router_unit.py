from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_current_merchant
from app.api.routers import analytics as analytics_mod
from app.main import app


@pytest_asyncio.fixture
async def analytics_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def fake_clickhouse_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MagicMock()
    store.summary = AsyncMock(
        return_value={
            "total_volume": Decimal("10"),
            "total_count": 2,
            "success_rate": 0.5,
            "avg_amount": Decimal("5"),
        }
    )
    store.timeline = AsyncMock(
        return_value=[
            {
                "bucket": datetime(2024, 1, 1, tzinfo=UTC),
                "total_volume": Decimal("1"),
                "total_count": 1,
            }
        ]
    )
    store.by_currency = AsyncMock(
        return_value=[
            {"currency": "RUB", "total_volume": Decimal("2"), "total_count": 2},
        ]
    )
    monkeypatch.setattr(
        analytics_mod,
        "ClickHouseEventStore",
        lambda: store,
    )


@pytest.fixture
def override_merchant() -> MagicMock:
    m = MagicMock()
    m.id = "merchant-1"

    async def _dep() -> MagicMock:
        return m

    app.dependency_overrides[get_current_merchant] = _dep
    yield m
    app.dependency_overrides.pop(get_current_merchant, None)


@pytest.mark.asyncio
async def test_analytics_summary_endpoint(
    analytics_client: AsyncClient,
    fake_clickhouse_store: None,
    override_merchant: MagicMock,
) -> None:
    r = await analytics_client.get("/analytics/summary?period=7d")
    assert r.status_code == 200
    assert r.json()["total_count"] == 2


@pytest.mark.asyncio
async def test_analytics_timeline_endpoint(
    analytics_client: AsyncClient,
    fake_clickhouse_store: None,
    override_merchant: MagicMock,
) -> None:
    r = await analytics_client.get("/analytics/timeline?period=7d&granularity=hour")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_analytics_by_currency_endpoint(
    analytics_client: AsyncClient,
    fake_clickhouse_store: None,
    override_merchant: MagicMock,
) -> None:
    r = await analytics_client.get("/analytics/by_currency?period=30d")
    assert r.status_code == 200
    assert r.json()["items"][0]["currency"] == "RUB"
