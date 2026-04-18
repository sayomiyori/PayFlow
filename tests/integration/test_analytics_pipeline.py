import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_current_merchant
from app.main import app
from app.workers.clickhouse_consumer import ClickHouseConsumerService


@dataclass
class _FakeKafkaMessage:
    value: bytes


@dataclass
class _ConsumerBackend:
    messages: list[_FakeKafkaMessage]
    committed_offset: int = 0


class _FakeKafkaConsumer:
    def __init__(self, backend: _ConsumerBackend):
        self.backend = backend
        self.cursor = backend.committed_offset

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def getmany(self, timeout_ms: int, max_records: int):  # noqa: ARG002
        batch = self.backend.messages[self.cursor : self.cursor + max_records]
        self.cursor += len(batch)
        return {"payments.events": batch}

    async def commit(self) -> None:
        self.backend.committed_offset = self.cursor

    def assignment(self):
        return set()

    def highwater(self, partition):  # noqa: ARG002
        return self.backend.committed_offset

    async def position(self, partition):  # noqa: ARG002
        return self.cursor


class _FakeEventStore:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    async def insert_events(self, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)

    async def summary(self, merchant_id: str, since: datetime) -> dict[str, Any]:  # noqa: ARG002
        filtered = [row for row in self.rows if row["merchant_id"] == merchant_id]
        total_count = len(filtered)
        total_volume = sum(
            (Decimal(str(row["amount"])) for row in filtered), Decimal("0")
        )
        success_count = len(
            [r for r in filtered if r["status"] in {"completed", "succeeded"}]
        )
        avg_amount = (total_volume / total_count) if total_count else Decimal("0")
        success_rate = (success_count / total_count) if total_count else 0.0
        return {
            "total_volume": total_volume,
            "total_count": total_count,
            "success_rate": success_rate,
            "avg_amount": avg_amount,
        }

    async def timeline(
        self,
        merchant_id: str,
        since: datetime,  # noqa: ARG002
        granularity: str,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        filtered = [row for row in self.rows if row["merchant_id"] == merchant_id]
        return [
            {
                "bucket": datetime.now(UTC),
                "total_volume": sum(
                    (Decimal(str(r["amount"])) for r in filtered), Decimal("0")
                ),
                "total_count": len(filtered),
            }
        ]

    async def by_currency(self, merchant_id: str, since: datetime):  # noqa: ARG002
        filtered = [row for row in self.rows if row["merchant_id"] == merchant_id]
        totals: dict[str, Decimal] = {}
        counts: dict[str, int] = {}
        for row in filtered:
            currency = str(row["currency"])
            totals[currency] = totals.get(currency, Decimal("0")) + Decimal(
                str(row["amount"])
            )
            counts[currency] = counts.get(currency, 0) + 1
        return [
            {"currency": c, "total_volume": totals[c], "total_count": counts[c]}
            for c in sorted(totals.keys())
        ]


def _make_event(merchant_id: str, payment_id: str) -> _FakeKafkaMessage:
    payload = {
        "tenant_schema": f"merchant_{merchant_id}",
        "event_type": "payment.created",
        "aggregate_id": payment_id,
        "payload": {
            "merchant_id": merchant_id,
            "payment_id": payment_id,
            "amount": "10.00",
            "currency": "RUB",
            "status": "completed",
        },
        "published_at": datetime.now(UTC).isoformat(),
    }
    return _FakeKafkaMessage(value=json.dumps(payload).encode("utf-8"))


@pytest.mark.asyncio
async def test_consumer_batch_insert_1000_events_all_inserted():
    # [ЧТО] Проверяем батчевую вставку sink: 1000 событий уходят в ClickHouse store.
    # [ПОЧЕМУ] Это гарантирует, что consumer корректно режет поток на батчи и не теряет записи.
    # [ОСТОРОЖНО] Тест использует fake consumer/store, интеграцию с реальным Kafka/CH проверяем отдельно.
    backend = _ConsumerBackend(
        messages=[_make_event("merchant_a", f"p{i}") for i in range(1000)],
    )
    fake_store = _FakeEventStore()
    consumer = _FakeKafkaConsumer(backend)
    service = ClickHouseConsumerService(event_store=fake_store, consumer=consumer)

    await service.process_batch(backend.messages[:500])
    await service.process_batch(backend.messages[500:])
    assert len(fake_store.rows) == 1000


@pytest.mark.asyncio
async def test_analytics_tenant_isolation_merchant_a_not_see_b(
    monkeypatch: pytest.MonkeyPatch,
):
    # [ЧТО] Проверяем tenant isolation в analytics API: каждый merchant видит только свои агрегаты.
    # [ПОЧЕМУ] merchant_id в WHERE — ключевой барьер изоляции в общем аналитическом хранилище.
    # [ОСТОРОЖНО] При любом рефакторинге store запросов этот тест должен оставаться регрессионным.
    from app.api.routers import analytics as analytics_router

    fake_store = _FakeEventStore()
    fake_store.rows.extend(
        [
            {
                "merchant_id": "merchant_a",
                "payment_id": "a1",
                "event_type": "payment.created",
                "amount": Decimal("10"),
                "currency": "RUB",
                "status": "completed",
                "created_at": datetime.now(UTC),
            },
            {
                "merchant_id": "merchant_b",
                "payment_id": "b1",
                "event_type": "payment.created",
                "amount": Decimal("20"),
                "currency": "USD",
                "status": "completed",
                "created_at": datetime.now(UTC),
            },
        ]
    )

    monkeypatch.setattr(
        analytics_router,
        "ClickHouseEventStore",
        lambda: fake_store,
    )

    async def merchant_a_dep():
        return SimpleNamespace(id="merchant_a")

    app.dependency_overrides[get_current_merchant] = merchant_a_dep
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/analytics/by_currency?period=7d")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == [
            {"currency": "RUB", "total_volume": "10", "total_count": 1}
        ]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_consumer_resume_after_restart_reads_from_last_offset():
    # [ЧТО] Проверяем resume после рестарта: consumer продолжает с последнего committed offset.
    # [ПОЧЕМУ] Это исключает дубли/потери при перезапуске sink-сервиса.
    # [ОСТОРОЖНО] В реальном Kafka commit сохраняется в broker, тут это смоделировано в fake backend.
    backend = _ConsumerBackend(
        messages=[_make_event("merchant_a", f"p{i}") for i in range(10)],
    )
    store_first = _FakeEventStore()
    service_first = ClickHouseConsumerService(
        event_store=store_first,
        consumer=_FakeKafkaConsumer(backend),
    )
    await service_first.process_batch(backend.messages[:6])
    backend.committed_offset = 6

    remaining_consumer = _FakeKafkaConsumer(backend)
    store_second = _FakeEventStore()
    service_second = ClickHouseConsumerService(
        event_store=store_second,
        consumer=remaining_consumer,
    )
    await service_second.consume_once()
    inserted_ids = {row["payment_id"] for row in store_second.rows}
    assert inserted_ids == {"p6", "p7", "p8", "p9"}
