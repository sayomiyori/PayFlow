from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.infrastructure.clickhouse.client import ClickHouseEventStore


@pytest.mark.asyncio
async def test_insert_events_empty_noop() -> None:
    client = MagicMock()
    store = ClickHouseEventStore(client=client)
    await store.insert_events([])
    client.execute.assert_not_called()


@pytest.mark.asyncio
async def test_summary_zero_rows_returns_zeros() -> None:
    client = MagicMock()
    client.execute.return_value = [(None, 0, None, 0)]
    store = ClickHouseEventStore(client=client)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    out = await store.summary("m1", since)
    assert out["total_count"] == 0
    assert out["total_volume"] == Decimal("0")
    assert out["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_summary_nonzero_computes_rates() -> None:
    client = MagicMock()
    client.execute.return_value = [(Decimal("10"), 4, Decimal("2.5"), 2)]
    store = ClickHouseEventStore(client=client)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    out = await store.summary("m1", since)
    assert out["total_count"] == 4
    assert out["success_rate"] == 0.5
    assert out["avg_amount"] == Decimal("2.5")


@pytest.mark.asyncio
async def test_timeline_hour_granularity_builds_query() -> None:
    client = MagicMock()
    client.execute.return_value = []
    store = ClickHouseEventStore(client=client)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    rows = await store.timeline("m1", since, "hour")
    assert rows == []
    call_sql = client.execute.call_args[0][0]
    assert "toStartOfHour" in call_sql


@pytest.mark.asyncio
async def test_by_currency_maps_rows() -> None:
    client = MagicMock()
    client.execute.return_value = [("RUB", Decimal("1"), 2)]
    store = ClickHouseEventStore(client=client)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    rows = await store.by_currency("m1", since)
    assert rows == [{"currency": "RUB", "total_volume": Decimal("1"), "total_count": 2}]


@pytest.mark.asyncio
async def test_insert_events_batches_execute() -> None:
    client = MagicMock()
    store = ClickHouseEventStore(client=client)
    rows = [
        {
            "merchant_id": "a",
            "payment_id": "p1",
            "event_type": "x",
            "amount": Decimal("1"),
            "currency": "RUB",
            "status": "ok",
            "created_at": datetime.now(UTC),
        }
    ]
    await store.insert_events(rows)
    client.execute.assert_called_once()


@pytest.mark.asyncio
async def test_timeline_date_bucket_datetime_combine() -> None:
    client = MagicMock()
    bucket = datetime(2024, 2, 1).date()
    client.execute.return_value = [(bucket, Decimal("3"), 1)]
    store = ClickHouseEventStore(client=client)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    rows = await store.timeline("m1", since, "day")
    assert len(rows) == 1
    assert rows[0]["total_volume"] == Decimal("3")
    assert rows[0]["bucket"].tzinfo == UTC
