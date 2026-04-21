import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers.clickhouse_consumer import (
    ClickHouseConsumerService,
    _extract_row,
    _safe_decimal,
)


def test_safe_decimal_invalid_returns_zero() -> None:
    assert _safe_decimal(None) == Decimal("0")
    assert _safe_decimal("not-a-number") == Decimal("0")


def test_extract_row_parses_kafka_payload() -> None:
    payload = {
        "event_type": "payment.created",
        "aggregate_id": "agg-1",
        "published_at": "2024-01-01T12:00:00Z",
        "payload": {
            "merchant_id": "m1",
            "payment_id": "p1",
            "amount": "10.5",
            "currency": "RUB",
            "status": "PaymentStatus.PENDING",
        },
    }
    raw = json.dumps(payload).encode()
    row = _extract_row(raw)
    assert row["merchant_id"] == "m1"
    assert row["amount"] == Decimal("10.5")
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_process_batch_commits_after_insert() -> None:
    store = MagicMock()
    store.insert_events = AsyncMock()
    consumer = MagicMock()
    consumer.commit = AsyncMock()
    svc = ClickHouseConsumerService(event_store=store, consumer=consumer)
    msg = SimpleNamespace(value=json.dumps({"event_type": "t", "payload": {}}).encode())
    n = await svc.process_batch([msg])
    assert n == 1
    store.insert_events.assert_awaited_once()
    consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_lag_metric_sums_partition_lag() -> None:
    store = MagicMock()
    store.insert_events = AsyncMock()
    consumer = MagicMock()
    partition = MagicMock()
    consumer.assignment = MagicMock(return_value=[partition])
    consumer.highwater = MagicMock(return_value=100)
    consumer.position = AsyncMock(return_value=40)
    svc = ClickHouseConsumerService(event_store=store, consumer=consumer)

    lag = await svc._update_lag_metric()
    assert lag == 60


@pytest.mark.asyncio
async def test_consume_once_empty_map_updates_lag_only() -> None:
    store = MagicMock()
    store.insert_events = AsyncMock()
    consumer = MagicMock()
    consumer.getmany = AsyncMock(return_value={})
    consumer.assignment = MagicMock(return_value=[])
    consumer.position = AsyncMock(return_value=0)
    svc = ClickHouseConsumerService(event_store=store, consumer=consumer)

    n = await svc.consume_once()
    assert n == 0
    store.insert_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_once_with_records_processes_batch() -> None:
    store = MagicMock()
    store.insert_events = AsyncMock()
    consumer = MagicMock()
    msg = SimpleNamespace(value=json.dumps({"event_type": "t", "payload": {}}).encode())
    consumer.getmany = AsyncMock(return_value={"p": [msg]})
    consumer.commit = AsyncMock()
    consumer.assignment = MagicMock(return_value=[])
    consumer.position = AsyncMock(return_value=0)
    svc = ClickHouseConsumerService(event_store=store, consumer=consumer)

    n = await svc.consume_once()
    assert n == 1
    store.insert_events.assert_awaited_once()
